"""자격증명 암호화 검증.

DB에는 Anthropic 키·Meta 토큰·오브젝트 스토리지 키가 들어간다. DFY로 고객 계정의
자격증명까지 받으면 평문 저장은 사고 한 번에 치명적이므로, 저장 시점에 암호화한다.
"""
import os
import sqlite3
import stat

import pytest

from branding.config.settings import Settings
from branding.db import SettingsStore, TokenRepository, init_db
from branding.security import (
    ENC_PREFIX, KEYFILE_NAME, SECRET_KEY_ENV, SecretBox, SecretsUnavailable,
    generate_key, is_encrypted,
)


@pytest.fixture(autouse=True)
def _no_ambient_key(monkeypatch):
    """호스트 환경변수가 테스트에 새어 들어오지 않게 한다."""
    monkeypatch.delenv(SECRET_KEY_ENV, raising=False)


# --- SecretBox ---

def test_round_trip_preserves_value():
    box = SecretBox(generate_key())
    assert box.decrypt(box.encrypt("sk-ant-비밀키")) == "sk-ant-비밀키"


def test_ciphertext_does_not_contain_plaintext():
    box = SecretBox(generate_key())
    encrypted = box.encrypt("EAAG-super-secret-token")
    assert "super-secret" not in encrypted
    assert is_encrypted(encrypted)
    assert encrypted.startswith(ENC_PREFIX)


def test_same_value_encrypts_differently_each_time():
    box = SecretBox(generate_key())
    assert box.encrypt("같은값") != box.encrypt("같은값")   # nonce가 매번 다름


def test_plaintext_values_pass_through_for_backward_compatibility():
    box = SecretBox(generate_key())
    assert box.decrypt("legacy-plaintext-token") == "legacy-plaintext-token"


def test_empty_values_are_left_alone():
    box = SecretBox(generate_key())
    assert box.encrypt("") == ""
    assert box.decrypt("") == ""
    assert box.decrypt(None) is None


def test_wrong_key_cannot_decrypt():
    encrypted = SecretBox(generate_key()).encrypt("비밀")
    with pytest.raises(SecretsUnavailable, match="복호화"):
        SecretBox(generate_key()).decrypt(encrypted)


def test_invalid_key_is_rejected_with_guidance():
    with pytest.raises(SecretsUnavailable, match=SECRET_KEY_ENV):
        SecretBox("not-a-valid-key")


def test_disabled_box_stores_plaintext_but_still_reads():
    box = SecretBox(None)
    assert box.enabled is False
    assert box.encrypt("값") == "값"
    assert box.decrypt("값") == "값"


def test_disabled_box_cannot_read_encrypted_values():
    encrypted = SecretBox(generate_key()).encrypt("비밀")
    with pytest.raises(SecretsUnavailable, match="복호화 키가 없습니다"):
        SecretBox(None).decrypt(encrypted)


# --- 키 해석 ---

def test_env_key_takes_precedence(tmp_path, monkeypatch):
    key = generate_key()
    monkeypatch.setenv(SECRET_KEY_ENV, key)
    box = SecretBox.for_data_dir(tmp_path)
    assert SecretBox(key).decrypt(box.encrypt("값")) == "값"
    assert not (tmp_path / KEYFILE_NAME).exists()   # 키파일을 만들지 않음


def test_keyfile_is_created_with_owner_only_permissions(tmp_path):
    SecretBox.for_data_dir(tmp_path)
    keyfile = tmp_path / KEYFILE_NAME
    assert keyfile.exists()
    assert stat.S_IMODE(keyfile.stat().st_mode) == 0o600


def test_keyfile_is_reused_across_instances(tmp_path):
    first = SecretBox.for_data_dir(tmp_path)
    encrypted = first.encrypt("지속되는 값")
    assert SecretBox.for_data_dir(tmp_path).decrypt(encrypted) == "지속되는 값"


# --- 저장소 통합 ---

def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return s


def _raw_column(db_path, table: str, column: str) -> list[str]:
    conn = sqlite3.connect(db_path)
    rows = conn.execute(f"SELECT {column} FROM {table}").fetchall()
    conn.close()
    return [r[0] for r in rows]


def test_settings_store_encrypts_at_rest(tmp_path):
    settings = _settings(tmp_path)
    store = SettingsStore(settings.db_path)
    store.set("anthropic_api_key", "sk-ant-실제키")

    # 읽을 때는 평문
    assert store.get("anthropic_api_key") == "sk-ant-실제키"
    assert store.all()["anthropic_api_key"] == "sk-ant-실제키"
    # DB 파일에는 평문이 없어야 한다
    stored = _raw_column(settings.db_path, "settings_store", "value")
    assert all(is_encrypted(v) for v in stored)
    assert "sk-ant-실제키" not in "".join(stored)


def test_token_store_encrypts_at_rest(tmp_path):
    settings = _settings(tmp_path)
    repo = TokenRepository(settings.db_path)
    repo.upsert("threads", "EAAG-실제토큰")

    assert repo.get_token("threads") == "EAAG-실제토큰"
    stored = _raw_column(settings.db_path, "token_store", "access_token")
    assert all(is_encrypted(v) for v in stored)
    assert "EAAG-실제토큰" not in "".join(stored)


def test_db_file_bytes_do_not_leak_secrets(tmp_path):
    """DB 파일이 통째로 유출돼도 값이 드러나지 않아야 한다."""
    settings = _settings(tmp_path)
    SettingsStore(settings.db_path).set("meta_access_token", "EAAG-leak-me")
    TokenRepository(settings.db_path).upsert("instagram", "EAAG-leak-me-too")

    blob = settings.db_path.read_bytes()
    assert b"EAAG-leak-me" not in blob
    assert b"EAAG-leak-me-too" not in blob


def test_existing_plaintext_rows_remain_readable(tmp_path):
    """암호화 도입 전 DB를 그대로 열 수 있어야 한다."""
    settings = _settings(tmp_path)
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO settings_store (key, value, updated_at) VALUES (?,?,?)",
        ("meta_ig_user_id", "17841400000000000", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        """INSERT INTO token_store (platform, access_token, token_type, updated_at)
           VALUES (?,?,?,?)""",
        ("threads", "legacy-plain-token", "long_lived", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    assert SettingsStore(settings.db_path).get("meta_ig_user_id") == "17841400000000000"
    assert TokenRepository(settings.db_path).get_token("threads") == "legacy-plain-token"


def test_migrate_encrypts_existing_plaintext(tmp_path):
    settings = _settings(tmp_path)
    conn = sqlite3.connect(settings.db_path)
    conn.execute(
        "INSERT INTO settings_store (key, value, updated_at) VALUES (?,?,?)",
        ("meta_access_token", "plain-secret", "2026-01-01T00:00:00+00:00"),
    )
    conn.execute(
        """INSERT INTO token_store (platform, access_token, token_type, updated_at)
           VALUES (?,?,?,?)""",
        ("instagram", "plain-token", "long_lived", "2026-01-01T00:00:00+00:00"),
    )
    conn.commit()
    conn.close()

    store, tokens = SettingsStore(settings.db_path), TokenRepository(settings.db_path)
    assert store.reencrypt_all() == ["meta_access_token"]
    assert tokens.reencrypt_all() == ["instagram"]

    # 값은 그대로 읽히고, 파일에는 남지 않는다
    assert store.get("meta_access_token") == "plain-secret"
    assert tokens.get_token("instagram") == "plain-token"
    assert b"plain-secret" not in settings.db_path.read_bytes()
    # 두 번째 실행은 바꿀 것이 없다
    assert store.reencrypt_all() == []
    assert tokens.reencrypt_all() == []
