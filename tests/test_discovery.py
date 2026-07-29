"""타깃 발굴 검증.

발굴·점수화까지만 자동화하고 실행은 사람이 한다(ToS 준수). 하루에 반응할 수 있는
양은 정해져 있으므로, 무엇부터 손대야 값진지를 점수가 제대로 갈라야 한다.
"""
import httpx
import pytest

from branding.config import load_brand_config
from branding.config.settings import Settings
from branding.db import HashtagQuotaRepository, TargetRepository, init_db
from branding.discovery import (
    AccountSignal, DiscoveryService, PostSignal, score_account, score_posts,
)
from branding.models import TargetCandidate, TargetKind, TargetStatus
from branding.models.enums import Platform
from branding.utils.time import now_utc


# --- 게시물 점수 (코호트 상대 평가) ---

def _p(pid: str, likes: int, comments: int = 0, age: float = 1.0) -> PostSignal:
    return PostSignal(external_id=pid, like_count=likes, comments_count=comments, age_days=age)


def test_higher_engagement_than_cohort_scores_higher():
    scored = score_posts([_p("a", 10), _p("b", 12), _p("c", 11), _p("viral", 200)])
    assert scored["viral"].score > scored["a"].score
    assert any("배 반응" in r for r in scored["viral"].reasons)


def test_absolute_numbers_do_not_matter_only_relative():
    """해시태그마다 반응 규모가 달라 절대값 비교는 의미가 없다."""
    small = score_posts([_p("a", 5), _p("b", 5), _p("top", 50)])
    large = score_posts([_p("a", 5000), _p("b", 5000), _p("top", 50000)])
    assert small["top"].score == large["top"].score


def test_crowded_posts_are_penalised():
    """댓글이 수백 개면 내 댓글이 묻힌다 — 반응 가치가 낮다."""
    quiet = score_posts([_p("x", 100, comments=10), _p("y", 100, comments=10)])
    crowded = score_posts([_p("x", 100, comments=900), _p("y", 100, comments=900)])
    assert crowded["x"].score < quiet["x"].score
    assert any("묻힐" in r for r in crowded["x"].reasons)


def test_recent_posts_score_higher_than_old_ones():
    fresh = score_posts([_p("a", 10), _p("b", 10), _p("t", 30, age=1)])
    stale = score_posts([_p("a", 10), _p("b", 10), _p("t", 30, age=60)])
    assert fresh["t"].score > stale["t"].score
    assert any("최근" in r for r in fresh["t"].reasons)


def test_empty_cohort_is_handled():
    assert score_posts([]) == {}


# --- 계정 점수 (팔로워 구간 + 참여율) ---

def test_account_in_target_range_scores_well():
    scored = score_account(AccountSignal("a", 5000, avg_likes=200, avg_comments=20), 500, 50000)
    assert scored.score >= 50
    assert any("목표 구간" in r for r in scored.reasons)


def test_account_below_range_is_deprioritised():
    scored = score_account(AccountSignal("tiny", 50, avg_likes=5, avg_comments=1), 500, 50000)
    assert scored.score < 30
    assert any("미만" in r for r in scored.reasons)


def test_account_above_range_is_deprioritised():
    """너무 큰 계정은 반응을 돌려받기 어렵다."""
    scored = score_account(AccountSignal("huge", 900000, avg_likes=9000, avg_comments=500),
                           500, 50000)
    assert scored.score <= 25
    assert any("초과" in r for r in scored.reasons)


def test_engagement_rate_separates_accounts_of_same_size():
    alive = score_account(AccountSignal("a", 10000, 400, 40), 500, 50000)
    dead = score_account(AccountSignal("b", 10000, 20, 1), 500, 50000)
    assert alive.score > dead.score


def test_account_without_followers_scores_zero():
    assert score_account(AccountSignal("x", 0), 500, 50000).score == 0.0


# --- 해시태그 주간 한도 ---

def _settings(tmp_path) -> Settings:
    s = Settings(data_dir=tmp_path, meta_ig_user_id="1784100", meta_access_token="tok")
    init_db(s.db_path)
    return s


def test_quota_counts_unique_hashtags(tmp_path):
    repo = HashtagQuotaRepository(_settings(tmp_path).db_path, limit=3)
    repo.record("창업")
    repo.record("창업")           # 같은 태그 재조회는 한도를 쓰지 않는다
    repo.record("자동화")
    assert repo.recent_unique() == {"창업", "자동화"}
    assert repo.remaining() == 1


def test_quota_allows_already_seen_hashtag_even_when_full(tmp_path):
    repo = HashtagQuotaRepository(_settings(tmp_path).db_path, limit=2)
    repo.record("a")
    repo.record("b")
    assert repo.remaining() == 0
    assert repo.allows("a") is True      # 이미 본 태그는 무료
    assert repo.allows("새태그") is False  # 새 태그는 막힌다


def test_hashtag_is_normalised(tmp_path):
    repo = HashtagQuotaRepository(_settings(tmp_path).db_path)
    repo.record("#창업")
    assert repo.recent_unique() == {"창업"}


# --- 저장소 ---

def _candidate(**kw) -> TargetCandidate:
    base = dict(platform=Platform.INSTAGRAM, kind=TargetKind.POST, external_id="m1",
                permalink="https://instagram.com/p/1", source="#창업", score=50.0)
    base.update(kw)
    return TargetCandidate(**base)


def test_rediscovering_updates_metrics_without_duplicating(tmp_path):
    repo = TargetRepository(_settings(tmp_path).db_path)
    repo.upsert(_candidate(like_count=10, score=40.0))
    again = repo.upsert(_candidate(like_count=99, score=80.0))

    assert again.like_count == 99
    assert again.score == 80.0
    assert len(repo.list_by_status(TargetStatus.NEW)) == 1   # 중복 없음


def test_human_decisions_survive_rediscovery(tmp_path):
    """사람이 처리한 항목이 재발굴로 되살아나면 같은 일을 두 번 하게 된다."""
    repo = TargetRepository(_settings(tmp_path).db_path)
    saved = repo.upsert(_candidate())
    repo.set_status(saved.id, TargetStatus.ACTIONED, note="댓글 남김")

    repo.upsert(_candidate(like_count=999))

    reloaded = repo.get_by_id(saved.id)
    assert reloaded.status == TargetStatus.ACTIONED
    assert reloaded.note == "댓글 남김"
    assert reloaded.like_count == 999          # 지표는 갱신됨


def test_listing_is_ordered_by_score(tmp_path):
    repo = TargetRepository(_settings(tmp_path).db_path)
    repo.upsert(_candidate(external_id="low", score=10.0))
    repo.upsert(_candidate(external_id="high", score=90.0))
    repo.upsert(_candidate(external_id="mid", score=50.0))

    assert [c.external_id for c in repo.list_by_status(TargetStatus.NEW)] == [
        "high", "mid", "low"
    ]


def test_status_transitions_record_action_time(tmp_path):
    repo = TargetRepository(_settings(tmp_path).db_path)
    saved = repo.upsert(_candidate())
    assert saved.actioned_at is None
    updated = repo.set_status(saved.id, TargetStatus.SKIPPED, note="니치 불일치")
    assert updated.status == TargetStatus.SKIPPED
    assert updated.actioned_at is not None
    assert repo.counts() == {"skipped": 1}


# --- 서비스 (Graph API 모킹) ---

@pytest.fixture
def brand():
    b = load_brand_config("brand/config.yaml")
    b.discovery.hashtags = ["창업"]
    b.discovery.seed_accounts = []
    return b


def _graph(handler, tmp_path, brand, **settings_kw) -> DiscoveryService:
    s = Settings(data_dir=tmp_path, meta_ig_user_id="1784100", meta_access_token="tok",
                 **settings_kw)
    init_db(s.db_path)
    return DiscoveryService(s, brand, transport=httpx.MockTransport(handler))


def _media(mid: str, likes: int, comments: int) -> dict:
    return {
        "id": mid, "caption": f"글 {mid}", "media_type": "IMAGE",
        "permalink": f"https://instagram.com/p/{mid}",
        "like_count": likes, "comments_count": comments,
        "timestamp": now_utc().isoformat(),
    }


def test_discover_saves_scored_candidates(tmp_path, brand):
    def handler(request):
        if "ig_hashtag_search" in request.url.path:
            return httpx.Response(200, json={"data": [{"id": "HT1"}]})
        if "top_media" in request.url.path:
            return httpx.Response(200, json={"data": [
                _media("a", 10, 2), _media("b", 12, 1), _media("viral", 400, 30),
            ]})
        return httpx.Response(404, json={"error": {"message": "unexpected"}})

    svc = _graph(handler, tmp_path, brand)
    report = svc.discover()

    assert report.hashtags_queried == ["창업"]
    assert len(report.candidates) == 3
    top = report.candidates[0]
    assert top.external_id == "viral"
    assert top.source == "#창업"
    assert top.permalink == "https://instagram.com/p/viral"
    assert top.reasons


def test_discover_respects_weekly_quota(tmp_path, brand):
    brand.discovery.hashtags = ["새태그"]
    brand.discovery.max_hashtag_queries_per_week = 1

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"id": "HT1"}]})

    svc = _graph(handler, tmp_path, brand)
    svc.quota.record("이미쓴태그")     # 한도 1개를 이미 소모

    report = svc.discover()

    assert report.hashtags_skipped == ["새태그"]
    assert report.hashtags_queried == []
    assert calls == []                 # 한도를 넘겨 호출하지 않는다


def test_api_error_on_one_hashtag_does_not_stop_others(tmp_path, brand):
    brand.discovery.hashtags = ["실패태그", "성공태그"]

    def handler(request):
        if "ig_hashtag_search" in request.url.path:
            # 한글은 URL 인코딩되므로 원문 대신 디코딩된 쿼리 파라미터로 판별한다
            if request.url.params.get("q") == "실패태그":
                return httpx.Response(400, json={"error": {"message": "bad hashtag"}})
            return httpx.Response(200, json={"data": [{"id": "HT2"}]})
        return httpx.Response(200, json={"data": [_media("ok", 50, 5)]})

    report = _graph(handler, tmp_path, brand).discover()

    assert any("실패태그" in e for e in report.errors)
    assert [c.external_id for c in report.candidates] == ["ok"]


def test_business_discovery_builds_account_candidate(tmp_path, brand):
    brand.discovery.hashtags = []
    brand.discovery.seed_accounts = ["coach_kim"]

    def handler(request):
        return httpx.Response(200, json={"business_discovery": {
            "username": "coach_kim", "followers_count": 8000, "media_count": 120,
            "media": {"data": [
                {"like_count": 300, "comments_count": 25, "permalink": "p1"},
                {"like_count": 260, "comments_count": 15, "permalink": "p2"},
            ]},
        }})

    report = _graph(handler, tmp_path, brand).discover()

    assert len(report.candidates) == 1
    account = report.candidates[0]
    assert account.kind == TargetKind.ACCOUNT
    assert account.username == "coach_kim"
    assert account.followers_count == 8000
    assert account.permalink == "https://www.instagram.com/coach_kim/"
    assert account.engagement_rate > 0
    assert account.score > 0


def test_checklist_returns_top_scoring_new_targets(tmp_path, brand):
    def handler(request):
        if "ig_hashtag_search" in request.url.path:
            return httpx.Response(200, json={"data": [{"id": "HT1"}]})
        return httpx.Response(200, json={"data": [
            _media(str(i), i * 10, 1) for i in range(1, 8)
        ]})

    svc = _graph(handler, tmp_path, brand)
    svc.discover()
    brand.discovery.daily_checklist = 3

    rows = svc.checklist()

    assert len(rows) == 3
    assert rows[0].score >= rows[-1].score
    assert all(c.status == TargetStatus.NEW for c in rows)


def test_missing_ig_user_id_is_reported(tmp_path, brand):
    from branding.publisher.base import MetaAPIError

    s = Settings(data_dir=tmp_path, meta_access_token="tok")   # IG user id 없음
    init_db(s.db_path)
    svc = DiscoveryService(s, brand)
    with pytest.raises(MetaAPIError, match="META_IG_USER_ID"):
        svc.search_hashtag_id("창업")
