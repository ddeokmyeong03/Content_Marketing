from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from branding.config.settings import Settings
from branding.db import (
    AccountMetricsRepository, MetricsRepository, PostRepository, init_db,
)
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc
from branding.web import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path)
    init_db(settings.db_path)
    pr = PostRepository(settings.db_path)
    # 검토 대기 1건
    pr.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.STARTUP_REALITY, topic="번아웃 이야기",
        content=PostContent(caption_ko="본문", cta="저장", chosen_hook="강한 훅",
                            engagement_score=84),
        status=PostStatus.DRAFT,
    ))
    return TestClient(create_app(settings)), settings


def test_dashboard_html_served(client):
    c, _ = client
    r = c.get("/")
    assert r.status_code == 200
    assert "운영 대시보드" in r.text


def test_stats_and_queue(client):
    c, _ = client
    stats = c.get("/api/stats").json()
    assert stats["counts"]["draft"] == 1

    rows = c.get("/api/queue?status=draft").json()
    assert len(rows) == 1
    assert rows[0]["topic"] == "번아웃 이야기"
    assert rows[0]["engagement_score"] == 84


def test_post_detail_and_approve(client):
    c, _ = client
    pid = c.get("/api/queue?status=draft").json()[0]["id"]

    detail = c.get(f"/api/posts/{pid}").json()
    assert detail["chosen_hook"] == "강한 훅"
    assert detail["caption_ko"] == "본문"

    res = c.post(f"/api/posts/{pid}/approve").json()
    assert res["status"] == "approved"
    # 재승인 시도는 충돌
    assert c.post(f"/api/posts/{pid}/approve").status_code == 409
    # 큐에서 approved로 이동
    assert len(c.get("/api/queue?status=approved").json()) == 1


def test_growth_endpoints(client):
    c, settings = client
    # 계정 스냅샷 + 발행 게시물 성과 추가
    ar = AccountMetricsRepository(settings.db_path)
    ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1000,
                                   fetched_at=now_utc() - timedelta(days=20)))
    ar.save_snapshot(AccountMetric(platform=Platform.INSTAGRAM, followers_count=1300))
    pr = PostRepository(settings.db_path)
    mr = MetricsRepository(settings.db_path)
    p = pr.save(Post(platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
                     content_pillar=ContentPillar.AUTOMATION_TIPS, topic="발행글",
                     content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
                     meta_post_id="m1", published_at=now_utc() - timedelta(days=5)))
    mr.save_snapshot(PostMetric(post_id=p.id, platform=Platform.INSTAGRAM, reach=5000, follows=200))

    att = c.get("/api/attribution").json()
    assert att[0]["follower_growth"] == 300
    assert c.get("/api/breakouts").status_code == 200
    assert c.get("/api/patterns").status_code == 200
