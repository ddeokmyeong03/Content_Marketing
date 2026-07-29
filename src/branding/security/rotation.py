"""마스터 키 로테이션 — 저장된 자격증명을 새 키로 다시 암호화한다.

키가 유출됐거나 정기 교체가 필요할 때, 저장된 값을 **옛 키로 읽어 새 키로 다시 쓴다**.
암호화 자체와 달리 이 작업은 중간에 멈추면 안 된다:

  일부 행만 새 키로 바뀌면 **어느 키로도 전체를 읽을 수 없다.** 옛 키는 새로 쓴 행을,
  새 키는 아직 안 바꾼 행을 복호화하지 못한다. 자격증명을 통째로 잃는 상황이다.

그래서 세 가지를 지킨다:
  1. **전부 읽고 나서 쓴다** — 옛 키가 틀렸으면 한 행도 건드리기 전에 실패한다
  2. **한 트랜잭션** — 도중에 죽으면 롤백되어 옛 키로 계속 읽힌다
  3. **커밋 전 검증** — 새 키로 전부 되읽어 원본과 같은지 확인하고 커밋한다

DB를 바꾼 뒤에는 키 파일·환경변수도 새 키로 갱신해야 한다. 그 순서와 실패 처리는
호출자(CLI)의 몫이며, `rotate_secrets` 는 DB만 책임진다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .crypto import SecretBox, SecretsUnavailable, is_encrypted

logger = logging.getLogger("branding.security")


def _connect(db_path: str | Path):
    # db 계층이 security 를 import 하므로 여기서는 지연 import 로 순환을 피한다
    from ..db.database import get_connection

    return get_connection(db_path)


@dataclass
class RotationResult:
    """무엇이 새 키로 바뀌었는가."""

    settings_keys: list[str] = field(default_factory=list)
    token_platforms: list[str] = field(default_factory=list)
    # 암호화 없이 평문으로 있던 값 — 로테이션이 마이그레이션까지 겸한다
    encrypted_from_plaintext: int = 0

    @property
    def total(self) -> int:
        return len(self.settings_keys) + len(self.token_platforms)


def rotate_secrets(
    db_path: str | Path,
    old_box: SecretBox,
    new_box: SecretBox,
) -> RotationResult:
    """저장된 모든 자격증명을 `old_box` 로 읽어 `new_box` 로 다시 쓴다.

    성공하면 커밋된 DB는 새 키로만 읽힌다. 실패하면 아무것도 바뀌지 않는다.
    """
    if not new_box.enabled:
        raise SecretsUnavailable(
            "새 키가 없어 로테이션할 수 없습니다 — 로테이션은 암호화를 끄는 용도가 아닙니다."
        )

    conn = _connect(db_path)
    try:
        # 1) 전부 평문으로 읽는다. 옛 키가 틀렸다면 여기서 끝난다(쓰기 전).
        setting_rows = conn.execute(
            "SELECT key, value FROM settings_store"
        ).fetchall()
        token_rows = conn.execute(
            "SELECT platform, access_token FROM token_store"
        ).fetchall()

        result = RotationResult()
        plain_settings: dict[str, str] = {}
        for row in setting_rows:
            if not row["value"]:
                continue
            if not is_encrypted(row["value"]):
                result.encrypted_from_plaintext += 1
            plain_settings[row["key"]] = old_box.decrypt(row["value"])
            result.settings_keys.append(row["key"])

        plain_tokens: dict[str, str] = {}
        for row in token_rows:
            if not row["access_token"]:
                continue
            if not is_encrypted(row["access_token"]):
                result.encrypted_from_plaintext += 1
            plain_tokens[row["platform"]] = old_box.decrypt(row["access_token"])
            result.token_platforms.append(row["platform"])

        # 2) 새 키로 다시 쓴다. updated_at 은 건드리지 않는다 — 값이 바뀐 게 아니다.
        for key, plain in plain_settings.items():
            conn.execute(
                "UPDATE settings_store SET value=? WHERE key=?",
                (new_box.encrypt(plain), key),
            )
        for platform, plain in plain_tokens.items():
            conn.execute(
                "UPDATE token_store SET access_token=? WHERE platform=?",
                (new_box.encrypt(plain), platform),
            )

        # 3) 커밋 전 검증 — 새 키로 전부 되읽어 원본과 같아야 한다
        _verify(conn, new_box, plain_settings, plain_tokens)

        conn.commit()
    except Exception:
        conn.rollback()   # 옛 키로 계속 읽히는 상태로 되돌린다
        raise
    finally:
        conn.close()

    logger.info(
        "키 로테이션 완료 — 설정 %d건, 토큰 %d건",
        len(result.settings_keys), len(result.token_platforms),
    )
    return result


def _verify(
    conn,
    new_box: SecretBox,
    plain_settings: dict[str, str],
    plain_tokens: dict[str, str],
) -> None:
    """새 키로 되읽어 원본과 일치하는지 확인 (아직 커밋 전)."""
    for row in conn.execute("SELECT key, value FROM settings_store"):
        expected = plain_settings.get(row["key"])
        if expected is None:
            continue
        if new_box.decrypt(row["value"]) != expected:
            raise SecretsUnavailable(
                f"로테이션 검증 실패 — 설정 '{row['key']}' 가 새 키로 복원되지 않습니다. "
                "변경을 되돌립니다."
            )
    for row in conn.execute("SELECT platform, access_token FROM token_store"):
        expected = plain_tokens.get(row["platform"])
        if expected is None:
            continue
        if new_box.decrypt(row["access_token"]) != expected:
            raise SecretsUnavailable(
                f"로테이션 검증 실패 — 토큰 '{row['platform']}' 가 새 키로 복원되지 "
                "않습니다. 변경을 되돌립니다."
            )


def rotation_preview(db_path: str | Path) -> tuple[int, int]:
    """로테이션 대상 건수 (설정, 토큰) — 확인 프롬프트용."""
    conn = _connect(db_path)
    try:
        settings_count = conn.execute(
            "SELECT COUNT(*) FROM settings_store WHERE value IS NOT NULL AND value != ''"
        ).fetchone()[0]
        tokens_count = conn.execute(
            "SELECT COUNT(*) FROM token_store "
            "WHERE access_token IS NOT NULL AND access_token != ''"
        ).fetchone()[0]
    finally:
        conn.close()
    return settings_count, tokens_count
