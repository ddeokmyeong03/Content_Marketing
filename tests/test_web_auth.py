"""대시보드 인증 검증.

대시보드는 API 키 등록·발행·승인이 가능한 운영 콘솔이다. 인증 없이 외부에 노출되면
계정을 통째로 내주는 것과 같으므로, '인증 없는 콘솔이 공개되는' 경로가 없어야 한다.
"""
import base64

import pytest
from fastapi.testclient import TestClient

from branding.config.settings import Settings
from branding.db import init_db
from branding.web import create_app
from branding.web.auth import is_loopback

PROTECTED_PATHS = ["/", "/api/stats", "/api/queue", "/api/config", "/api/breakouts"]


def _client(tmp_path, **kw) -> TestClient:
    settings = Settings(data_dir=tmp_path, **kw)
    init_db(settings.db_path)
    return TestClient(create_app(settings))


def _basic(user: str, password: str) -> dict:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


# --- 바인드 주소 판정 (CLI 가드가 쓰는 규칙) ---

@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1", "", "127.0.0.5"])
def test_loopback_hosts_are_recognized(host):
    assert is_loopback(host) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.0.10", "10.0.0.1", "example.com"])
def test_external_hosts_are_recognized(host):
    assert is_loopback(host) is False


# --- 인증 미설정 (기존 로컬 사용 방식) ---

def test_without_password_dashboard_stays_open(tmp_path):
    """로컬 사용을 막지 않는다 — 외부 노출은 CLI가 별도로 차단한다."""
    client = _client(tmp_path)
    assert client.get("/api/stats").status_code == 200


# --- 인증 설정 시 ---

def test_all_endpoints_require_credentials(tmp_path):
    client = _client(tmp_path, web_auth_password="s3cret")
    for path in PROTECTED_PATHS:
        assert client.get(path).status_code == 401, path


def test_challenge_header_is_sent(tmp_path):
    client = _client(tmp_path, web_auth_password="s3cret")
    r = client.get("/api/stats")
    assert r.status_code == 401
    assert r.headers["www-authenticate"] == "Basic"


def test_correct_credentials_are_accepted(tmp_path):
    client = _client(tmp_path, web_auth_password="s3cret")
    r = client.get("/api/stats", headers=_basic("admin", "s3cret"))
    assert r.status_code == 200


def test_custom_user_is_honored(tmp_path):
    client = _client(tmp_path, web_auth_user="operator", web_auth_password="s3cret")
    assert client.get("/api/stats", headers=_basic("operator", "s3cret")).status_code == 200
    assert client.get("/api/stats", headers=_basic("admin", "s3cret")).status_code == 401


def test_non_ascii_credentials_are_warned_about(tmp_path, caplog):
    """HTTP Basic은 ASCII만 실어 나른다 — 조용히 잠기지 않도록 미리 알린다."""
    with caplog.at_level("WARNING", logger="branding.web.auth"):
        client = _client(tmp_path, web_auth_password="비밀번호")
    assert "ASCII" in caplog.text
    # 실제로 인증이 불가능하다는 점도 확인 (경고가 괜한 말이 아님)
    assert client.get("/api/stats", headers=_basic("admin", "비밀번호")).status_code == 401


@pytest.mark.parametrize(
    "user,password",
    [("admin", "wrong"), ("wrong", "s3cret"), ("wrong", "wrong"), ("", "")],
)
def test_bad_credentials_are_rejected(tmp_path, user, password):
    client = _client(tmp_path, web_auth_password="s3cret")
    assert client.get("/api/stats", headers=_basic(user, password)).status_code == 401


def test_write_endpoints_are_protected_too(tmp_path):
    """읽기만 막고 쓰기를 열어두면 의미가 없다."""
    client = _client(tmp_path, web_auth_password="s3cret")
    assert client.post("/api/posts/1/approve").status_code == 401
    assert client.post("/api/config", json={"anthropic_api_key": "x"}).status_code == 401


def test_blank_password_is_treated_as_disabled(tmp_path):
    client = _client(tmp_path, web_auth_password="   ")
    assert client.get("/api/stats").status_code == 200
