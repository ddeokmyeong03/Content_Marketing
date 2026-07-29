"""마스터 키 로테이션 검증.

키가 유출되면 갈아끼워야 한다. 그런데 로테이션은 절반만 되면 **어느 키로도 전체를
읽을 수 없는** 상태를 만든다 — 옛 키는 새로 쓴 행을, 새 키는 안 바꾼 행을 못 읽는다.
자격증명을 통째로 잃는 것이라 실패는 반드시 "아무것도 안 바뀜"이어야 한다.

여기서 지키려는 불변식: **로테이션은 전부 성공하거나 전혀 바뀌지 않는다.**
"""
import sqlite3
import stat

import pytest

from branding.config.settings import Settings
from branding.db import SettingsStore, TokenRepository, init_db
from branding.security import (
    KEYFILE_NAME, SECRET_KEY_ENV, SecretBox, SecretsUnavailable, generate_key,
    is_encrypted, read_keyfile, rotate_secrets, rotation_preview, write_keyfile,
)


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch):
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)


def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return s


def _seed(db_path, key: str) -> dict:
    """주어진 키로 암호화된 자격증명을 심고 평문을 돌려준다."""
    box = SecretBox(key)
    values = {"anthropic_api_key": "sk-ant-원본키", "meta_ig_user_id": "17841400000000000"}
    store = SettingsStore(db_path, box=box)
    for k, v in values.items():
        store.set(k, v)
    TokenRepository(db_path, box=box).upsert("threads", "EAAG-원본토큰")
    return values


def _raw(db_path, table: str, column: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    conn.close()
    return [r[0] for r in rows]


# --- 정상 로테이션 ---

def test_rotation_reencrypts_everything_with_the_new_key(tmp_path):
    settings = _settings(tmp_path)
    old, new = generate_key(), generate_key()
    values = _seed(settings.db_path, old)

    result = rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    assert result.total == 3
    assert sorted(result.settings_keys) == ["anthropic_api_key", "meta_ig_user_id"]
    assert result.token_platforms == ["threads"]

    # 새 키로 값이 그대로 읽힌다
    store = SettingsStore(settings.db_path, box=SecretBox(new))
    assert store.all() == values
    assert TokenRepository(settings.db_path, box=SecretBox(new)).get_token("threads") == (
        "EAAG-원본토큰"
    )


def test_old_key_can_no_longer_read_after_rotation(tmp_path):
    """교체의 핵심 — 유출된 옛 키가 더 이상 쓸모없어야 한다."""
    settings = _settings(tmp_path)
    old, new = generate_key(), generate_key()
    _seed(settings.db_path, old)

    rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    with pytest.raises(SecretsUnavailable, match="복호화"):
        SettingsStore(settings.db_path, box=SecretBox(old)).all()


def test_ciphertext_actually_changes(tmp_path):
    settings = _settings(tmp_path)
    old, new = generate_key(), generate_key()
    _seed(settings.db_path, old)
    before = _raw(settings.db_path, "settings_store", "value")

    rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    after = _raw(settings.db_path, "settings_store", "value")
    assert all(is_encrypted(v) for v in after)
    assert set(before).isdisjoint(after)
    assert "sk-ant-원본키" not in settings.db_path.read_bytes().decode("utf-8", "ignore")


def test_rotation_absorbs_plaintext_values(tmp_path):
    """평문으로 남아 있던 값도 새 키로 암호화된다 — migrate 를 겸한다."""
    settings = _settings(tmp_path)
    old, new = generate_key(), generate_key()
    _seed(settings.db_path, old)
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO settings_store (key, value, updated_at) VALUES (?,?,?)",
        ("meta_access_token", "평문토큰", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    result = rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    assert result.encrypted_from_plaintext == 1
    store = SettingsStore(settings.db_path, box=SecretBox(new))
    assert store.get("meta_access_token") == "평문토큰"
    assert all(is_encrypted(v) for v in _raw(settings.db_path, "settings_store", "value"))


def test_rotating_a_plaintext_only_db_works_without_old_key(tmp_path):
    """암호화 이전 DB를 바로 새 키로 올릴 수 있어야 한다."""
    settings = _settings(tmp_path)
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO settings_store (key, value, updated_at) VALUES (?,?,?)",
        ("meta_access_token", "평문", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()
    new = generate_key()

    rotate_secrets(settings.db_path, SecretBox(None), SecretBox(new))

    assert SettingsStore(settings.db_path, box=SecretBox(new)).get("meta_access_token") == "평문"


def test_empty_db_rotates_without_error(tmp_path):
    settings = _settings(tmp_path)
    result = rotate_secrets(settings.db_path, SecretBox(None), SecretBox(generate_key()))
    assert result.total == 0


# --- 실패는 아무것도 바꾸지 않는다 ---

def test_wrong_old_key_changes_nothing(tmp_path):
    """가장 흔한 사고 — 옛 키를 잘못 넣는 것. 단 한 행도 건드리면 안 된다."""
    settings = _settings(tmp_path)
    old, wrong, new = generate_key(), generate_key(), generate_key()
    values = _seed(settings.db_path, old)
    before = _raw(settings.db_path, "settings_store", "value")

    with pytest.raises(SecretsUnavailable):
        rotate_secrets(settings.db_path, SecretBox(wrong), SecretBox(new))

    assert _raw(settings.db_path, "settings_store", "value") == before
    # 옛 키로 여전히 멀쩡하게 읽힌다
    assert SettingsStore(settings.db_path, box=SecretBox(old)).all() == values


def test_one_unreadable_row_aborts_the_whole_rotation(tmp_path):
    """여러 행 중 하나만 못 읽어도 나머지를 바꾸면 안 된다 — 쓰기 전에 멈춘다."""
    settings = _settings(tmp_path)
    old, other, new = generate_key(), generate_key(), generate_key()
    _seed(settings.db_path, old)
    # 다른 키로 암호화된 행을 섞어 둔다 — 중간에서 복호화가 깨진다
    SettingsStore(settings.db_path, box=SecretBox(other)).set("s3_secret_access_key", "다른키값")
    before = _raw(settings.db_path, "settings_store", "value")

    with pytest.raises(SecretsUnavailable):
        rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    assert _raw(settings.db_path, "settings_store", "value") == before
    assert SettingsStore(settings.db_path, box=SecretBox(old)).get("anthropic_api_key") == (
        "sk-ant-원본키"
    )


class CorruptingBox:
    """암호화는 되지만 되읽으면 값이 달라지는 상자 — 검증 단계를 터뜨린다.

    쓰기가 이미 일어난 뒤에 실패하는 유일한 경로이므로, 진짜 롤백은 이걸로만 확인된다.
    """

    enabled = True

    def __init__(self):
        self.box = SecretBox(generate_key())

    def encrypt(self, plaintext: str) -> str:
        return self.box.encrypt(plaintext)

    def decrypt(self, value):
        return "엉뚱한값"


def test_verification_failure_after_writes_rolls_everything_back(tmp_path):
    """커밋 전 검증이 깨지면, 이미 쓴 행까지 전부 되돌아가야 한다."""
    settings = _settings(tmp_path)
    old = generate_key()
    values = _seed(settings.db_path, old)
    before = _raw(settings.db_path, "settings_store", "value")

    with pytest.raises(SecretsUnavailable, match="검증 실패"):
        rotate_secrets(settings.db_path, SecretBox(old), CorruptingBox())

    # 커밋되지 않았으므로 DB는 손대기 전 그대로다
    assert _raw(settings.db_path, "settings_store", "value") == before
    assert SettingsStore(settings.db_path, box=SecretBox(old)).all() == values
    assert TokenRepository(settings.db_path, box=SecretBox(old)).get_token("threads") == (
        "EAAG-원본토큰"
    )


def test_rotation_without_a_new_key_is_refused(tmp_path):
    """로테이션으로 암호화를 끄는 길을 열어 두지 않는다."""
    settings = _settings(tmp_path)
    old = generate_key()
    _seed(settings.db_path, old)

    with pytest.raises(SecretsUnavailable, match="새 키가 없어"):
        rotate_secrets(settings.db_path, SecretBox(old), SecretBox(None))

    assert SettingsStore(settings.db_path, box=SecretBox(old)).get("anthropic_api_key")


def test_token_metadata_survives_rotation(tmp_path):
    """토큰 값만 바뀌고 platform·token_type 은 그대로여야 한다."""
    settings = _settings(tmp_path)
    old, new = generate_key(), generate_key()
    _seed(settings.db_path, old)

    rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))

    conn = sqlite3.connect(settings.db_path)
    row = conn.execute("SELECT platform, token_type FROM token_store").fetchone()
    conn.close()
    assert row == ("threads", "long_lived")


# --- 미리보기 ---

def test_preview_counts_what_will_be_rotated(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings.db_path, generate_key())
    assert rotation_preview(settings.db_path) == (2, 1)


# --- 키 파일 교체 ---

def test_write_keyfile_replaces_with_owner_only_permissions(tmp_path):
    write_keyfile(tmp_path, "첫키")
    path = write_keyfile(tmp_path, "둘째키")

    assert path.read_text() == "둘째키"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert read_keyfile(tmp_path) == "둘째키"
    assert not (tmp_path / f"{KEYFILE_NAME}.tmp").exists()   # 임시 파일이 남지 않음


def test_read_keyfile_returns_none_when_absent(tmp_path):
    assert read_keyfile(tmp_path) is None


def test_rotation_then_keyfile_update_is_readable_by_default_resolution(tmp_path):
    """CLI 가 하는 순서 그대로 — DB 교체 후 키 파일 갱신하면 평소처럼 읽혀야 한다."""
    settings = _settings(tmp_path)
    old = generate_key()
    write_keyfile(tmp_path, old)
    values = _seed(settings.db_path, old)
    new = generate_key()

    rotate_secrets(settings.db_path, SecretBox(old), SecretBox(new))
    write_keyfile(tmp_path, new)

    # 키를 명시하지 않고(기본 해석 경로) 열어도 그대로 읽힌다
    assert SettingsStore(settings.db_path).all() == values
