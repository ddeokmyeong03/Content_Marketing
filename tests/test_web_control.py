import pytest
from fastapi.testclient import TestClient

from branding.config.settings import Settings
from branding.db import SettingsStore, init_db
from branding.web import create_app
from branding.web.app import resolve_settings


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


# --- 액션 엔드포인트 (키 없이 graceful) ---

def test_generate_action_without_key(ctx):
    c, _ = ctx
    r = c.post("/api/actions/generate").json()
    assert r["ok"] is False
    assert "키" in r["error"]


def test_collect_action_runs_without_published(ctx):
    c, _ = ctx
    r = c.post("/api/actions/collect").json()
    assert r["ok"] is True          # 발행 게시물이 없어도 성공(0건)


def test_generate_action_uses_db_registered_key(ctx, monkeypatch):
    """DB에 키를 등록하면 액션이 그 키로 동작(생성 함수는 목업)."""
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
    r = c.post("/api/actions/generate").json()
    assert r["ok"] is True
    assert captured["key"] == "sk-db"       # DB 등록 키가 서비스에 전달됨
