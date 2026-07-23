from datetime import timedelta

import httpx

from branding.auth import TokenRefresher
from branding.config.settings import Settings
from branding.db import TokenRepository, init_db
from branding.models.enums import Platform
from branding.utils.time import now_utc


def _settings(tmp_path, **kw) -> Settings:
    s = Settings(data_dir=tmp_path, **kw)
    init_db(s.db_path)
    return s


def test_threads_refresh_updates_token(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        assert "refresh_access_token" in str(request.url)
        assert "th_refresh_token" in str(request.url)
        return httpx.Response(200, json={"access_token": "NEWTOK", "expires_in": 5183944})

    s = _settings(tmp_path)
    repo = TokenRepository(s.db_path)
    repo.upsert("threads", "OLDTOK", expires_at=now_utc() + timedelta(days=1))  # 임박

    r = TokenRefresher(s, transport=httpx.MockTransport(handler)).refresh_if_needed(
        Platform.THREADS
    )

    assert r.refreshed
    assert repo.get_token("threads") == "NEWTOK"
    assert repo.get_expiry("threads") - now_utc() > timedelta(days=50)


def test_skip_when_expiry_far_in_future(tmp_path):
    def handler(request):  # 호출되면 실패
        raise AssertionError("만료 여유가 있으면 API를 호출하면 안 됨")

    s = _settings(tmp_path)
    repo = TokenRepository(s.db_path)
    repo.upsert("threads", "TOK", expires_at=now_utc() + timedelta(days=30))

    r = TokenRefresher(s, transport=httpx.MockTransport(handler)).refresh_if_needed(
        Platform.THREADS, threshold_days=7
    )
    assert not r.refreshed


def test_meta_refresh_requires_app_credentials(tmp_path):
    def handler(request):
        raise AssertionError("자격증명 없으면 호출 안 됨")

    s = _settings(tmp_path)  # app_id/secret 미설정
    repo = TokenRepository(s.db_path)
    repo.upsert("instagram", "TOK", expires_at=now_utc() + timedelta(days=1))

    r = TokenRefresher(s, transport=httpx.MockTransport(handler)).refresh_if_needed(
        Platform.INSTAGRAM
    )
    assert not r.refreshed
    assert "미설정" in r.reason
