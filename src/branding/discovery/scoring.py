"""타깃 우선순위 점수 (순수 계산).

하루에 반응할 수 있는 양은 정해져 있다. 무엇부터 손대야 가장 값진지를 점수로 정한다.

게시물(댓글·좋아요 대상)의 좋은 조건:
  - 같은 해시태그 안에서 **상대적으로** 반응이 좋다 → 살아있는 청중이 모여 있다
  - 너무 크지 않다 → 댓글 수천 개짜리 글에서 내 댓글은 보이지 않는다
  - 최근이다 → 아직 피드에 노출 중이라 내 반응이 눈에 띈다

계정(팔로우·소통 대상)의 좋은 조건:
  - 팔로워가 목표 구간에 있다 → 너무 크면 반응이 없고, 너무 작으면 도달이 적다
  - 참여율이 높다 → 팔로워가 실제로 반응하는 계정
"""
from __future__ import annotations

from dataclasses import dataclass, field

# 댓글이 이 수를 넘으면 내 댓글이 묻힌다 — 반응 가치가 급격히 떨어진다
CROWDED_COMMENTS = 300
RECENT_DAYS = 3


@dataclass
class PostSignal:
    external_id: str
    like_count: int = 0
    comments_count: int = 0
    age_days: float = 0.0


@dataclass
class AccountSignal:
    username: str
    followers_count: int = 0
    avg_likes: float = 0.0
    avg_comments: float = 0.0


@dataclass
class Scored:
    score: float                                    # 0-100
    reasons: list[str] = field(default_factory=list)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def engagement_of(signal: PostSignal) -> int:
    return signal.like_count + signal.comments_count


def score_posts(signals: list[PostSignal]) -> dict[str, Scored]:
    """같은 해시태그 코호트 안에서 상대 평가한다.

    해시태그마다 반응 규모가 달라서 절대값 비교는 의미가 없다 —
    중앙값 대비 몇 배인지가 '이 판에서 잘 된 글'을 가른다.
    """
    if not signals:
        return {}

    engagements = [float(engagement_of(s)) for s in signals]
    median = _median(engagements) or 1.0

    out: dict[str, Scored] = {}
    for s in signals:
        reasons: list[str] = []
        ratio = engagement_of(s) / median
        # 중앙값의 3배면 만점에 가깝게
        base = min(70.0, ratio / 3.0 * 70.0)
        if ratio >= 1.5:
            reasons.append(f"해시태그 평균 대비 {ratio:.1f}배 반응")

        if s.age_days <= RECENT_DAYS:
            base += 20
            reasons.append(f"최근 {s.age_days:.0f}일 이내")

        if s.comments_count > CROWDED_COMMENTS:
            base *= 0.4
            reasons.append(f"댓글 {s.comments_count}개 — 내 댓글이 묻힐 수 있음")
        elif s.comments_count > 0:
            base += 10
            reasons.append("댓글이 오가는 중")

        out[s.external_id] = Scored(round(min(100.0, max(0.0, base)), 1), reasons)
    return out


def score_account(
    signal: AccountSignal, min_followers: int, max_followers: int
) -> Scored:
    """팔로워 구간 적합도와 참여율로 평가."""
    reasons: list[str] = []
    followers = signal.followers_count
    if followers <= 0:
        return Scored(0.0, ["팔로워 정보 없음"])

    if followers < min_followers:
        return Scored(
            round(max(0.0, 25 * followers / max(1, min_followers)), 1),
            [f"팔로워 {followers} — 목표 구간({min_followers}~{max_followers}) 미만"],
        )
    if followers > max_followers:
        return Scored(
            20.0,
            [f"팔로워 {followers} — 목표 구간 초과, 반응을 받기 어려움"],
        )

    reasons.append(f"팔로워 {followers} — 목표 구간")
    base = 50.0

    engagement_rate = (signal.avg_likes + signal.avg_comments) / followers
    # 참여율 3%면 만점 구간
    base += min(50.0, engagement_rate / 0.03 * 50.0)
    if engagement_rate >= 0.03:
        reasons.append(f"참여율 {engagement_rate:.1%} — 청중이 살아있음")
    elif engagement_rate > 0:
        reasons.append(f"참여율 {engagement_rate:.1%}")

    return Scored(round(min(100.0, base), 1), reasons)
