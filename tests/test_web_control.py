import time

import pytest
from fastapi.testclient import TestClient

from branding.config.settings import Settings
from branding.db import SettingsStore, init_db
from branding.web import create_app
from branding.web.app import resolve_settings


def _run_job(c, name, timeout=5.0):
    """액션 잡을 시작하고 종료될 때까지 폴링해 최종 상태를 반환."""
    job_id = c.post(f"/api/actions/{name}").json()["job_id"]
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(f"/api/jobs/{job_id}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise AssertionError("잡이 시간 내에 끝나지 않음")


@pytest.fixture
def ctx(tmp_path):
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return TestClient(create_app(s)), s


# --- SettingsStore + resolve ---

def test_settings_store_roundtrip(tmp_path):
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    store = SettingsStore(s.db_path)
    store.set("meta_ig_user_id", "IG123")
    assert store.get("meta_ig_user_id") == "IG123"
    assert store.all()["meta_ig_user_id"] == "IG123"


def test_resolve_overlays_store_over_env(tmp_path):
    s = Settings(data_dir=tmp_path, anthropic_api_key="")
    init_db(s.db_path)
    store = SettingsStore(s.db_path)
    store.set("anthropic_api_key", "sk-from-db")
    store.set("unknown_field", "ignored")     # 모델에 없는 키는 무시
    resolved = resolve_settings(s, store)
    assert resolved.anthropic_api_key == "sk-from-db"
    assert not hasattr(resolved, "unknown_field")


# --- config 엔드포인트 (마스킹) ---

def test_config_get_masks_secrets(ctx):
    c, _ = ctx
    c.post("/api/config", json={"anthropic_api_key": "sk-secret-123456789",
                                "meta_ig_user_id": "IG42"})
    cfg = c.get("/api/config").json()
    assert cfg["anthropic_api_key"]["set"] is True
    assert "masked" in cfg["anthropic_api_key"]
    assert "sk-secret-123456789" not in str(cfg)     # 원문 노출 안 됨
    assert cfg["meta_ig_user_id"]["value"] == "IG42"  # 비밀 아님 → 노출


def test_config_post_ignores_blank_and_unknown(ctx):
    c, _ = ctx
    r = c.post("/api/config", json={"meta_app_id": "APP1", "meta_ig_user_id": "",
                                    "bogus": "x"}).json()
    assert r["changed"] == ["meta_app_id"]


# --- 액션 엔드포인트 (백그라운드 잡) ---

def test_generate_job_without_key_errors(ctx):
    c, _ = ctx
    j = _run_job(c, "generate")
    assert j["status"] == "error"
    assert "키" in j["error"]


def test_collect_job_runs_without_published(ctx):
    c, _ = ctx
    j = _run_job(c, "collect")
    assert j["status"] == "done"        # 발행 게시물이 없어도 성공(0건)


def test_unknown_action_404(ctx):
    c, _ = ctx
    assert c.post("/api/actions/bogus").status_code == 404


def test_job_status_404(ctx):
    c, _ = ctx
    assert c.get("/api/jobs/nonexistent").status_code == 404


def test_generate_job_uses_db_registered_key(ctx, monkeypatch):
    """DB에 키를 등록하면 잡이 그 키로 동작(생성 함수는 목업)."""
    c, s = ctx
    c.post("/api/config", json={"anthropic_api_key": "sk-db"})

    import branding.web.app as webapp
    captured = {}

    def fake_generate(settings, brand, **kw):
        captured["key"] = settings.anthropic_api_key
        class R:
            class plan: theme_ko = "테마"
            posts = [1, 2]
        return R()

    monkeypatch.setattr(webapp, "generate_week", fake_generate)
    j = _run_job(c, "generate")
    assert j["status"] == "done"
    assert captured["key"] == "sk-db"       # DB 등록 키가 서비스에 전달됨
    assert "2개 생성" in j["result"]["message"]


def test_growth_series_endpoint(ctx):
    c, s = ctx
    from datetime import timedelta
    from branding.db import AccountMetricsRepository
    from branding.models import AccountMetric
    from branding.models.enums import Platform
    from branding.utils.time import now_utc
    ar = AccountMetricsRepository(s.db_path)
    ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1000,
                                   fetched_at=now_utc() - timedelta(days=10)))
    ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1120))
    data = c.get("/api/growth-series?platform=instagram").json()
    assert len(data["points"]) == 2
    assert data["points"][-1]["followers"] == 1120
