from datetime import timedelta

import httpx

from branding.config.settings import Settings
from branding.db import AccountMetricsRepository, MetricsRepository, PostRepository, init_db
from branding.db.database import _apply_migrations, get_connection
from branding.insights import InsightsService
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc


def _settings(tmp_path, **kw) -> Settings:
    s = Settings(data_dir=tmp_path, meta_access_token="tok", **kw)
    init_db(s.db_path)
    return s


# --- 계정 스냅샷 저장/성장 ---

def test_account_repo_snapshot_latest_and_growth(tmp_path):
    s = _settings(tmp_path)
    repo = AccountMetricsRepository(s.db_path)
    base = now_utc() - timedelta(days=20)
    repo.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1000,
                                     fetched_at=base))
    repo.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1250,
                                     reach=8000, fetched_at=now_utc()))

    latest = repo.latest(Platform.INSTAGRAM)
    assert latest.followers_count == 1250
    assert latest.reach == 8000
    assert repo.follower_growth(Platform.INSTAGRAM, days=30) == 250


def test_follower_growth_needs_two_points(tmp_path):
    s = _settings(tmp_path)
    repo = AccountMetricsRepository(s.db_path)
    repo.save_snapshot(AccountMetric(platform=Platform.THREADS, followers_count=500))
    assert repo.follower_growth(Platform.THREADS, days=30) is None


# --- 확장된 게시물 지표 라운드트립 ---

def test_post_metric_growth_fields_roundtrip(tmp_path):
    s = _settings(tmp_path)
    prepo = PostRepository(s.db_path)
    mrepo = MetricsRepository(s.db_path)
    post = prepo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="t",
        content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
        meta_post_id="m1",
    ))
    mrepo.save_snapshot(PostMetric(
        post_id=post.id, platform=Platform.INSTAGRAM,
        reach=5000, saved=120, shares=40, profile_visits=90, follows=35,
        total_interactions=300,
    ))
    latest = mrepo.latest_for_post(post.id)
    assert latest.profile_visits == 90
    assert latest.follows == 35
    assert latest.total_interactions == 300


# --- 마이그레이션: 기존 테이블에 신규 컬럼 추가 ---

def test_migration_adds_missing_columns(tmp_path):
    db = tmp_path / "legacy.db"
    conn = get_connection(db)
    # 신규 컬럼이 없는 구버전 post_metrics 생성
    conn.execute("""CREATE TABLE post_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, post_id INTEGER, platform TEXT,
        fetched_at DATETIME, likes INTEGER, comments INTEGER, shares INTEGER,
        saved INTEGER, reach INTEGER, views INTEGER, engagement_rate REAL, raw_json TEXT)""")
    conn.commit()
    _apply_migrations(conn)
    conn.commit()
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(post_metrics)")}
    conn.close()
    assert {"profile_visits", "follows", "total_interactions"} <= cols


# --- 계정 인사이트 수집 ---

def test_fetch_account_instagram(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "insights" in url:
            return httpx.Response(200, json={"data": [
                {"name": "reach", "values": [{"value": 12000}]},
                {"name": "profile_views", "values": [{"value": 350}]},
            ]})
        return httpx.Response(200, json={"followers_count": 2048})

    s = _settings(tmp_path, meta_ig_user_id="IG1")
    svc = InsightsService(s, transport=httpx.MockTransport(handler))
    m = svc.fetch_account(Platform.INSTAGRAM)
    assert m.followers_count == 2048
    assert m.reach == 12000
    assert m.profile_views == 350


def test_sync_account_stores_snapshot(tmp_path):
    def handler(request):
        url = str(request.url)
        if "threads_insights" in url:
            return httpx.Response(200, json={"data": [
                {"name": "followers_count", "total_value": {"value": 777}},
                {"name": "views", "total_value": {"value": 9000}},
            ]})
        return httpx.Response(200, json={"data": []})

    s = _settings(tmp_path, meta_threads_user_id="TH1")
    svc = InsightsService(s, transport=httpx.MockTransport(handler))
    collected = svc.sync_account()
    assert len(collected) == 1
    latest = AccountMetricsRepository(s.db_path).latest(Platform.THREADS)
    assert latest.followers_count == 777
    assert latest.views == 9000
