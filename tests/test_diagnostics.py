import httpx
import pytest

from branding.config import resolve_settings
from branding.config.settings import Settings
from branding.db import SettingsStore, init_db
from branding.diagnostics import Diagnostics


def _settings(tmp_path, **kw) -> Settings:
    # 환경변수(META_ACCESS_TOKEN 등)가 새어 들어오지 않도록 기본값을 명시
    base = {"anthropic_api_key": "", "meta_access_token": "",
            "meta_ig_user_id": "", "meta_threads_user_id": ""}
    base.update(kw)
    s = Settings(data_dir=tmp_path, **base)
    init_db(s.db_path)
    return s


# --- Threads: 실제로 겪은 두 가지 에러 재현 ---

def test_threads_wrong_user_id_is_detected_and_fixed(tmp_path):
    """핸들('auto._.duck')을 ID로 넣은 경우 → 올바른 숫자 ID를 찾아 안내/수정."""
    def handler(request):
        return httpx.Response(200, json={"id": "17841400000000000", "username": "auto._.duck"})

    s = _settings(tmp_path, meta_access_token="tok", meta_threads_user_id="auto._.duck")
    d = Diagnostics(s, transport=httpx.MockTransport(handler))

    c = d.check_threads()
    assert c.status == "warn"
    assert "17841400000000000" in c.hint          # 올바른 ID 안내

    c2 = d.check_threads(autofix=True)
    assert c2.status == "ok"
    assert SettingsStore(s.db_path).get("meta_threads_user_id") == "17841400000000000"


def test_threads_failed_to_decrypt_gives_token_type_hint(tmp_path):
    """'Failed to decrypt' → Threads 전용 토큰이 아니라는 힌트."""
    def handler(request):
        return httpx.Response(400, json={"error": {"message": "Failed to decrypt"}})

    s = _settings(tmp_path, meta_access_token="wrong-kind")
    c = Diagnostics(s, transport=httpx.MockTransport(handler)).check_threads()
    assert c.status == "fail"
    assert "Threads" in c.hint and "threads_basic" in c.hint


def test_threads_invalid_oauth_hints_copy_problem(tmp_path):
    def handler(request):
        return httpx.Response(400, json={"error": {
            "message": "Invalid OAuth access token - Cannot parse access token"}})

    s = _settings(tmp_path, meta_access_token="broken")
    c = Diagnostics(s, transport=httpx.MockTransport(handler)).check_threads()
    assert c.status == "fail"
    assert "복사" in c.hint


def test_threads_skipped_without_token(tmp_path):
    s = _settings(tmp_path)
    c = Diagnostics(s).check_threads()
    assert c.status == "skip"


# --- Anthropic ---

def test_anthropic_ok(tmp_path):
    def handler(request):
        assert request.headers["x-api-key"] == "sk-good"
        return httpx.Response(200, json={"data": []})

    s = _settings(tmp_path, anthropic_api_key="sk-good")
    c = Diagnostics(s, transport=httpx.MockTransport(handler)).check_anthropic()
    assert c.status == "ok"


def test_anthropic_401_is_fail(tmp_path):
    def handler(request):
        return httpx.Response(401, json={"error": {"message": "invalid x-api-key"}})

    s = _settings(tmp_path, anthropic_api_key="sk-bad")
    c = Diagnostics(s, transport=httpx.MockTransport(handler)).check_anthropic()
    assert c.status == "fail"
    assert "발급" in c.hint


def test_anthropic_missing_key(tmp_path):
    c = Diagnostics(_settings(tmp_path)).check_anthropic()
    assert c.status == "fail"


# --- Instagram 자동 탐색 ---

def test_instagram_discovers_business_account(tmp_path):
    def handler(request):
        url = str(request.url)
        if "me/accounts" in url:
            return httpx.Response(200, json={"data": [{"id": "PAGE1"}]})
        if "PAGE1" in url:
            return httpx.Response(200, json={"instagram_business_account": {"id": "IG999"}})
        return httpx.Response(400, json={"error": {"message": "nope"}})

    s = _settings(tmp_path, meta_access_token="tok")
    d = Diagnostics(s, transport=httpx.MockTransport(handler))
    c = d.check_instagram(autofix=True)
    assert c.status == "ok"
    assert SettingsStore(s.db_path).get("meta_ig_user_id") == "IG999"


# --- 통합 + 런타임 해석 ---

def test_run_all_returns_all_checks(tmp_path):
    s = _settings(tmp_path)
    checks = Diagnostics(s).run_all()
    names = [c.name for c in checks]
    assert "Anthropic API" in names and "Threads 연결" in names
    assert "발행 준비" in names


def test_resolve_settings_shared_helper(tmp_path):
    s = _settings(tmp_path)
    SettingsStore(s.db_path).set("meta_threads_user_id", "12345")
    assert resolve_settings(s).meta_threads_user_id == "12345"
