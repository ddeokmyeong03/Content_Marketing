"""표본이 적은 초기 계정에서의 브레이크아웃 판정 검증.

z-score는 분포가 있어야 의미가 있다. 신규 DFY 고객처럼 게시물이 몇 개뿐인
계정에서 '통계적으로 근거 없는 확정 판정'을 내리지 않고, 잠정 판정과 신뢰도로
정직하게 구분하는지 확인한다.
"""
from datetime import timedelta

from branding.analysis import (
    MIN_SAMPLES_ZSCORE,
    MODE_INSUFFICIENT,
    MODE_PROVISIONAL,
    MODE_ZSCORE,
    BreakoutService,
    MetricInput,
    confidence_for,
    detect_breakouts,
    detection_mode,
)
from branding.config.settings import Settings
from branding.db import (
    AccountMetricsRepository, MetricsRepository, PostRepository, init_db,
)
from branding.models import AccountMetric, Post, PostContent, PostMetric
from branding.models.enums import ContentPillar, MediaType, Platform, PostStatus
from branding.utils.time import now_utc


def _normal(post_id: int, followers: int = 1000) -> MetricInput:
    return MetricInput(
        post_id=post_id, reach=followers, shares=2, saved=5, follows=1,
        total_interactions=30, followers_at_post=followers,
    )


def _viral(post_id: int, followers: int = 1000) -> MetricInput:
    return MetricInput(
        post_id=post_id, reach=8000, shares=400, saved=600, follows=300,
        total_interactions=3000, followers_at_post=followers,
    )


# --- 모드·신뢰도 판정 ---

def test_detection_mode_by_sample_size():
    assert detection_mode(0) == MODE_INSUFFICIENT
    assert detection_mode(2) == MODE_INSUFFICIENT
    assert detection_mode(3) == MODE_PROVISIONAL
    assert detection_mode(7) == MODE_PROVISIONAL
    assert detection_mode(8) == MODE_ZSCORE
    assert detection_mode(50) == MODE_ZSCORE


def test_confidence_rises_with_sample_size():
    assert confidence_for(2) == 0                     # 판정 불가
    assert 20 <= confidence_for(3) < 50               # 잠정
    assert confidence_for(7) > confidence_for(3)
    assert confidence_for(8) >= 60                    # 확정 판정 시작
    assert confidence_for(30) == 100
    assert confidence_for(500) == 100                 # 상한


# --- 표본 부족 시 확정 판정을 내리지 않는다 ---

def test_too_few_posts_yields_no_breakout():
    items = [_normal(1), _viral(2)]                   # 2개 — 비교 불가
    results = detect_breakouts(items)

    assert all(r.mode == MODE_INSUFFICIENT for r in results)
    assert all(not r.is_breakout for r in results)
    assert all(r.confidence == 0 for r in results)
    assert all(r.sample_size == 2 for r in results)


def test_small_sample_flags_outlier_as_provisional_not_confirmed():
    items = [_normal(i) for i in range(1, 5)] + [_viral(99)]   # 5개
    results = detect_breakouts(items)
    top = results[0]

    assert top.post_id == 99
    assert top.is_breakout is True
    assert top.is_provisional is True                 # 확정이 아니라 잠정
    assert top.mode == MODE_PROVISIONAL
    assert 0 < top.confidence < 60                    # 낮은 신뢰도로 표기
    assert top.ratios                                 # 중앙값 대비 배수로 판정
    assert top.z_scores == {}                         # z-score는 쓰지 않음
    assert all(not r.is_breakout for r in results if r.post_id != 99)


def test_small_sample_without_outlier_has_no_breakout():
    results = detect_breakouts([_normal(i) for i in range(1, 6)])
    assert all(r.mode == MODE_PROVISIONAL for r in results)
    assert all(not r.is_breakout for r in results)


def test_sufficient_sample_uses_zscore_and_full_confidence():
    items = [_normal(i) for i in range(1, 11)] + [_viral(99)]  # 11개
    results = detect_breakouts(items)
    top = results[0]

    assert top.post_id == 99
    assert top.mode == MODE_ZSCORE
    assert top.is_provisional is False
    assert top.confidence >= 60
    assert top.z_scores                               # z-score 기반 판정


def test_min_samples_is_configurable():
    items = [_normal(i) for i in range(1, 5)] + [_viral(99)]   # 5개
    # 임계값을 낮추면 같은 표본도 확정 판정 모드로 처리된다
    results = detect_breakouts(items, min_samples=4)
    assert all(r.mode == MODE_ZSCORE for r in results)


# --- 서비스 계층: 판정 가능 여부 진단 ---

def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path)
    init_db(s.db_path)
    return s


def _seed(settings: Settings, count: int) -> None:
    prepo = PostRepository(settings.db_path)
    mrepo = MetricsRepository(settings.db_path)
    arepo = AccountMetricsRepository(settings.db_path)
    arepo.save_snapshot(AccountMetric(
        platform=Platform.INSTAGRAM, followers_count=1000,
        fetched_at=now_utc() - timedelta(days=10),
    ))
    for i in range(count):
        p = prepo.save(Post(
            platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
            content_pillar=ContentPillar.AUTOMATION_TIPS, topic=f"post{i}",
            content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
            meta_post_id=f"m-{i}", published_at=now_utc() - timedelta(days=5),
        ))
        mrepo.save_snapshot(PostMetric(
            post_id=p.id, platform=Platform.INSTAGRAM, reach=1000, shares=2,
            follows=1, saved=5, total_interactions=100,
        ))


def test_coverage_reports_shortfall_for_new_account(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, count=4)

    coverage = BreakoutService(settings).coverage(weeks=8)

    assert len(coverage) == 1
    cov = coverage[0]
    assert cov.platform == Platform.INSTAGRAM
    assert cov.sample_size == 4
    assert cov.mode == MODE_PROVISIONAL
    assert cov.needed_for_zscore == MIN_SAMPLES_ZSCORE - 4   # 정식 판정까지 남은 개수


def test_coverage_reports_ready_when_sample_is_sufficient(tmp_path):
    settings = _settings(tmp_path)
    _seed(settings, count=10)

    cov = BreakoutService(settings).coverage(weeks=8)[0]

    assert cov.mode == MODE_ZSCORE
    assert cov.needed_for_zscore == 0


def test_breakouts_only_can_exclude_provisional(tmp_path):
    """AI 역설계처럼 비용이 드는 소비자는 약한 신호를 걸러낼 수 있어야 한다."""
    settings = _settings(tmp_path)
    _seed(settings, count=4)
    prepo = PostRepository(settings.db_path)
    mrepo = MetricsRepository(settings.db_path)
    viral = prepo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="VIRAL",
        content=PostContent(caption_ko="c", cta=""), status=PostStatus.PUBLISHED,
        meta_post_id="m-viral", published_at=now_utc() - timedelta(days=5),
    ))
    mrepo.save_snapshot(PostMetric(
        post_id=viral.id, platform=Platform.INSTAGRAM, reach=9000, shares=500,
        follows=350, saved=700, total_interactions=3000,
    ))

    svc = BreakoutService(settings)
    assert [r.post.topic for r in svc.breakouts_only(weeks=8)] == ["VIRAL"]
    assert svc.breakouts_only(weeks=8, include_provisional=False) == []
