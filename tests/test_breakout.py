from branding.analysis import MetricInput, compute_rates, detect_breakouts
from branding.config.settings import Settings
from branding.db import (
    AccountMetricsRepository, MetricsRepository, PostRepository, init_db,
)
from branding.analysis import BreakoutService
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc
from datetime import timedelta


# --- 순수 탐지 로직 ---

def test_compute_rates_normalizes_by_followers_and_reach():
    r = compute_rates(MetricInput(
        post_id=1, reach=1000, shares=50, saved=100, follows=30,
        total_interactions=400, followers_at_post=500,
    ))
    assert r["reach_rate"] == 2.0        # 1000/500
    assert r["share_rate"] == 0.05       # 50/1000
    assert r["follow_rate"] == 0.03      # 30/1000


def test_compute_rates_skips_missing_denominators():
    r = compute_rates(MetricInput(post_id=1, reach=0, followers_at_post=None))
    assert r == {}                        # 팔로워·도달 없으면 지표 없음


def _normal(post_id: int, followers: int) -> MetricInput:
    # 평범한 게시물: 도달=팔로워, 낮은 상호작용
    return MetricInput(
        post_id=post_id, reach=followers, shares=2, saved=5, follows=1,
        total_interactions=30, followers_at_post=followers,
    )


def test_detects_clear_outlier_as_breakout():
    items = [_normal(i, 1000) for i in range(1, 11)]
    # 확실한 이상치: 도달·공유·팔로우가 압도적
    items.append(MetricInput(
        post_id=99, reach=8000, shares=400, saved=600, follows=300,
        total_interactions=3000, followers_at_post=1000,
    ))
    results = detect_breakouts(items)
    top = results[0]
    assert top.post_id == 99
    assert top.is_breakout
    assert top.breakout_score > 0
    assert "reach_rate" in top.reasons or "follow_rate" in top.reasons
    # 평범한 게시물은 브레이크아웃 아님
    assert all(not r.is_breakout for r in results if r.post_id != 99)


def test_uniform_population_has_no_breakout():
    items = [_normal(i, 1000) for i in range(1, 9)]
    results = detect_breakouts(items)
    assert all(not r.is_breakout for r in results)   # MAD=0 → z=0


# --- 서비스 조립 (DB 연동) ---

def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return s


def test_breakout_service_assembles_and_flags(tmp_path):
    s = _settings(tmp_path)
    prepo = PostRepository(s.db_path)
    mrepo = MetricsRepository(s.db_path)
    arepo = AccountMetricsRepository(s.db_path)
    arepo.save_snapshot(AccountMetric(
        platform=Platform.INSTAGRAM, followers_count=1000,
        fetched_at=now_utc() - timedelta(days=10),
    ))

    def add(topic, reach, shares, follows, saved):
        p = prepo.save(Post(
            platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
            content_pillar=ContentPillar.AUTOMATION_TIPS, topic=topic,
            content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
            meta_post_id=f"m-{topic}", published_at=now_utc() - timedelta(days=5),
        ))
        mrepo.save_snapshot(PostMetric(
            post_id=p.id, platform=Platform.INSTAGRAM, reach=reach, shares=shares,
            follows=follows, saved=saved, total_interactions=reach // 10,
        ))

    for i in range(8):
        add(f"normal{i}", reach=1000, shares=2, follows=1, saved=5)
    add("VIRAL", reach=9000, shares=500, follows=350, saved=700)

    rows = BreakoutService(s).breakouts_only(weeks=8)
    assert len(rows) == 1
    assert rows[0].post.topic == "VIRAL"
    assert rows[0].result.breakout_score > 0
