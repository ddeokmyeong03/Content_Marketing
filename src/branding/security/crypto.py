"""자격증명 암호화 (저장 시점).

DB에는 Anthropic 키·Meta 토큰·오브젝트 스토리지 키가 들어간다. DFY로 **고객 계정의**
자격증명까지 받게 되면 sqlite 평문 저장은 사고 한 번에 치명적이다. 파일이 백업·복사·
공유되는 흔한 경로에서 값이 그대로 드러나지 않도록 저장 시점에 암호화한다.

무엇을 막고 무엇을 못 막는가:
  - 막는다: DB 파일 유출·백업 노출·실수로 저장소에 커밋
  - 못 막는다: 실행 중인 호스트 전체가 장악된 경우 (키가 같은 호스트에 있으므로)

키 해석 순서:
  1. `BRANDING_SECRET_KEY` 환경변수 (권장 — 키를 DB와 다른 곳에 둘 수 있다)
  2. `{data_dir}/.secret_key` 파일 (없으면 0600 권한으로 자동 생성)

기존 평문 DB와 호환된다 — 접두사가 없는 값은 평문으로 간주해 그대로 읽고,
다음 쓰기에서 암호화된다(`branding secrets migrate` 로 일괄 전환 가능).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger("branding.security")

SECRET_KEY_ENV = "BRANDING_SECRET_KEY"
KEYFILE_NAME = ".secret_key"
ENC_PREFIX = "enc:v1:"

INSTALL_HINT = (
    "자격증명 암호화에는 cryptography가 필요합니다:\n  pip install -e '.'"
)


class SecretsUnavailable(RuntimeError):
    """암호화를 쓸 수 없음 (라이브러리 없음·키 오류)."""


def is_encrypted(value: str) -> bool:
    return isinstance(value, str) and value.startswith(ENC_PREFIX)


def generate_key() -> str:
    """새 마스터 키 생성 (Fernet 키, urlsafe base64)."""
    try:
        from cryptography.fernet import Fernet
    except ImportError as e:
        raise SecretsUnavailable(INSTALL_HINT) from e
    return Fernet.generate_key().decode()


def _read_or_create_keyfile(data_dir: Path) -> str:
    keyfile = Path(data_dir) / KEYFILE_NAME
    if keyfile.exists():
        return keyfile.read_text(encoding="utf-8").strip()

    key = generate_key()
    keyfile.parent.mkdir(parents=True, exist_ok=True)
    # 먼저 좁은 권한으로 만들고 쓴다 (생성과 권한 설정 사이의 틈을 없앰)
    fd = os.open(keyfile, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, key.encode("utf-8"))
    finally:
        os.close(fd)
    logger.warning(
        "자격증명 암호화 키를 새로 만들었습니다: %s — 이 파일을 잃어버리면 "
        "저장된 키·토큰을 복호화할 수 없습니다. 백업하거나 %s 환경변수로 관리하세요.",
        keyfile, SECRET_KEY_ENV,
    )
    return key


class SecretBox:
    """값을 암호화해 저장하고 읽을 때 복호화한다.

    평문(접두사 없는 값)은 그대로 돌려주므로 기존 DB가 깨지지 않는다.
    """

    def __init__(self, key: Optional[str]):
        self._fernet = None
        if not key:
            return
        try:
            from cryptography.fernet import Fernet
        except ImportError as e:
            raise SecretsUnavailable(INSTALL_HINT) from e
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except Exception as e:  # noqa: BLE001 - 잘못된 키를 한 종류로 안내
            raise SecretsUnavailable(
                f"{SECRET_KEY_ENV} 가 올바른 키가 아닙니다. "
                "`branding secrets init` 으로 새 키를 만들 수 있습니다. ({e})"
            ) from e

    # --- 생성 ---

    @classmethod
    def for_data_dir(cls, data_dir: Path | str) -> "SecretBox":
        """환경변수 → 키파일 순으로 키를 해석해 만든다."""
        env_key = os.environ.get(SECRET_KEY_ENV, "").strip()
        if env_key:
            return cls(env_key)
        try:
            return cls(_read_or_create_keyfile(Path(data_dir)))
        except SecretsUnavailable:
            raise
        except OSError as e:
            # 키파일을 만들 수 없는 환경 — 평문으로 계속하되 분명히 경고한다
            logger.warning(
                "암호화 키 파일을 준비하지 못해 자격증명을 평문으로 저장합니다 (%s). "
                "%s 환경변수를 설정하세요.", e, SECRET_KEY_ENV,
            )
            return cls(None)

    @classmethod
    def for_db_path(cls, db_path: Path | str) -> "SecretBox":
        return cls.for_data_dir(Path(db_path).parent)

    # --- 사용 ---

    @property
    def enabled(self) -> bool:
        return self._fernet is not None

    def encrypt(self, plaintext: str) -> str:
        if not plaintext or not self.enabled:
            return plaintext
        token = self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
        return f"{ENC_PREFIX}{token}"

    def decrypt(self, value: Optional[str]) -> Optional[str]:
        """저장된 값을 평문으로. 암호화되지 않은 값은 그대로 돌려준다."""
        if not value or not is_encrypted(value):
            return value
        if not self.enabled:
            raise SecretsUnavailable(
                "암호화된 값이 저장돼 있으나 복호화 키가 없습니다. "
                f"{SECRET_KEY_ENV} 환경변수 또는 {KEYFILE_NAME} 파일을 확인하세요."
            )
        from cryptography.fernet import InvalidToken

        payload = value[len(ENC_PREFIX):].encode("utf-8")
        try:
            return self._fernet.decrypt(payload).decode("utf-8")
        except InvalidToken as e:
            raise SecretsUnavailable(
                "저장된 자격증명을 복호화하지 못했습니다 — 키가 바뀌었을 수 있습니다. "
                f"({KEYFILE_NAME} 또는 {SECRET_KEY_ENV} 확인)"
            ) from e
