"""브레이크아웃 탐지 (순수 계산).

팔로워 대비 정규화한 게시물 지표를 로버스트 z-score로 평가해, 계정의 최근
분포 대비 압도적으로 뜬 게시물을 판정한다. DB·API에 의존하지 않아 단독 테스트 가능.

정규화 지표 (게시 시점 팔로워/도달 기준):
  reach_rate       = reach / followers_at_post   (팔로워 밖 확산)
  share_rate       = shares / reach
  save_rate        = saved / reach
  follow_rate      = follows / reach              (성장 직결)
  interaction_rate = total_interactions / reach
성장·확산 신호(reach/share/follow)에 가중치를 더 준다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# 지표별 가중치 — 오디언스 확장/성장 신호를 우선
WEIGHTS: dict[str, float] = {
    "reach_rate": 1.4,
    "share_rate": 1.3,
    "follow_rate": 1.5,
    "save_rate": 1.0,
    "interaction_rate": 0.8,
}

Z_THRESHOLD = 2.5   # 이 가중 z 이상이면 브레이크아웃
Z_CLAMP = 5.0       # z 상한 (점수 스케일링용)
_MAD_SCALE = 1.4826  # 정규분포에서 MAD→표준편차 환산 상수


@dataclass
class MetricInput:
    post_id: int
    reach: int = 0
    shares: int = 0
    saved: int = 0
    follows: int = 0
    total_interactions: int = 0
    likes: int = 0
    comments: int = 0
    followers_at_post: Optional[int] = None


@dataclass
class BreakoutResult:
    post_id: int
    breakout_score: float           # 0-100
    is_breakout: bool
    rates: dict[str, float] = field(default_factory=dict)
    z_scores: dict[str, float] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)  # 이상치를 일으킨 지표(내림차순)


def _median(xs: list[float]) -> float:
    s = sorted(xs)
    n = len(s)
    if n == 0:
        return 0.0
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2


def _mad(xs: list[float], med: float) -> float:
    return _median([abs(x - med) for x in xs])


def _stdev(xs: list[float], center: float) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    return (sum((x - center) ** 2 for x in xs) / n) ** 0.5


def _dispersion(xs: list[float], med: float) -> float:
    """MAD 기반 척도. MAD=0(다수 동일값)이면 표준편차로 폴백해 이상치 탐지력 유지."""
    mad = _mad(xs, med)
    if mad > 0:
        return _MAD_SCALE * mad
    return _stdev(xs, med)


def _robust_z(x: float, med: float, scale: float) -> float:
    if scale <= 0:
        return 0.0
    return (x - med) / scale


def compute_rates(item: MetricInput) -> dict[str, float]:
    """게시물의 정규화 지표. 분모가 없으면 해당 지표는 제외."""
    rates: dict[str, float] = {}
    if item.followers_at_post:
        rates["reach_rate"] = item.reach / item.followers_at_post
    if item.reach:
        rates["share_rate"] = item.shares / item.reach
        rates["save_rate"] = item.saved / item.reach
        rates["follow_rate"] = item.follows / item.reach
        interactions = item.total_interactions or (
            item.likes + item.comments + item.shares + item.saved
        )
        rates["interaction_rate"] = interactions / item.reach
    return rates


def detect_breakouts(
    items: list[MetricInput],
    z_threshold: float = Z_THRESHOLD,
    z_clamp: float = Z_CLAMP,
) -> list[BreakoutResult]:
    """동일 계정/플랫폼 게시물 집합에 대해 브레이크아웃 판정.

    반환은 breakout_score 내림차순.
    """
    rates_by_post = {it.post_id: compute_rates(it) for it in items}

    # 지표별 분포(중앙값·척도)를 전체 집합에서 계산
    baselines: dict[str, tuple[float, float]] = {}
    for metric in WEIGHTS:
        vals = [r[metric] for r in rates_by_post.values() if metric in r]
        if vals:
            med = _median(vals)
            baselines[metric] = (med, _dispersion(vals, med))

    results: list[BreakoutResult] = []
    for it in items:
        rates = rates_by_post[it.post_id]
        z_scores: dict[str, float] = {}
        weight_sum = 0.0
        weighted_pos = 0.0
        for metric, weight in WEIGHTS.items():
            if metric not in rates or metric not in baselines:
                continue
            med, scale = baselines[metric]
            z = _robust_z(rates[metric], med, scale)
            z_scores[metric] = round(z, 3)
            weight_sum += weight
            weighted_pos += weight * max(0.0, z)

        weighted_z = weighted_pos / weight_sum if weight_sum else 0.0
        score = round(min(100.0, weighted_z / z_clamp * 100), 1)
        reasons = sorted(
            (m for m, z in z_scores.items() if z >= z_threshold),
            key=lambda m: z_scores[m],
            reverse=True,
        )
        results.append(
            BreakoutResult(
                post_id=it.post_id,
                breakout_score=score,
                is_breakout=weighted_z >= z_threshold,
                rates={k: round(v, 4) for k, v in rates.items()},
                z_scores=z_scores,
                reasons=reasons,
            )
        )

    results.sort(key=lambda r: r.breakout_score, reverse=True)
    return results
