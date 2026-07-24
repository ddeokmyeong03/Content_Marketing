"""성장 귀인 (순수 계산).

기간 내 계정 팔로워 순증가를, 그 기간에 발행된 게시물들에 '전환 propensity'로
분배해 "이 게시물이 데려온 추정 팔로워 수"를 산출한다.

- Instagram: 게시물별 follows(직접 팔로우) 지표 → 강한 직접 신호
- Threads: 게시물별 follows 없음 → 상호작용(좋아요+댓글+공유+저장)을 대리 신호로 사용

두 경우를 하나의 모델로 통합: 각 게시물의 propensity 가중치로 실제 관측된
계정 순증가를 분배(합계 = 관측 순증가). DB·API에 의존하지 않아 단독 테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PostAttrInput:
    post_id: int
    follows: int = 0        # 게시물 직접 팔로우 (IG)
    interactions: int = 0   # 대리 신호 (Threads 등): likes+comments+shares+saved


@dataclass
class AttributionResult:
    post_id: int
    weight: float                  # 분배 가중치
    attributed_followers: float    # 추정 유입 팔로워
    direct_follows: int            # 직접 팔로우(IG)
    method: str                    # "direct"(follows 기반) | "modeled"(상호작용 대리)


def _weight(item: PostAttrInput) -> tuple[float, str]:
    """propensity 가중치와 방식. follows가 있으면 직접, 없으면 상호작용 대리."""
    if item.follows > 0:
        return float(item.follows), "direct"
    return float(item.interactions), "modeled"


def attribute(items: list[PostAttrInput], total_growth: int) -> list[AttributionResult]:
    """관측된 팔로워 순증가(total_growth)를 게시물 propensity로 분배.

    attributed_followers 합계 == total_growth (가중치 합이 0이면 균등 분배).
    total_growth<=0 이면 모두 0.
    """
    weights = [_weight(it) for it in items]
    weight_sum = sum(w for w, _ in weights)
    n = len(items)

    results: list[AttributionResult] = []
    for it, (w, method) in zip(items, weights):
        if total_growth <= 0 or n == 0:
            attributed = 0.0
        elif weight_sum > 0:
            attributed = total_growth * w / weight_sum
        else:
            attributed = total_growth / n  # 신호가 전무하면 균등 분배
        results.append(
            AttributionResult(
                post_id=it.post_id,
                weight=round(w, 3),
                attributed_followers=round(attributed, 1),
                direct_follows=it.follows,
                method=method,
            )
        )
    results.sort(key=lambda r: r.attributed_followers, reverse=True)
    return results
