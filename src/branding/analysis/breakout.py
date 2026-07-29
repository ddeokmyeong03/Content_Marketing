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

## 표본이 적을 때 (콜드스타트)

z-score는 분포가 있어야 의미가 있다. 게시물이 몇 개뿐인 신규 계정에서는
중앙값·MAD가 사실상 무작위라 판정이 신뢰할 수 없다. 그래서 표본 수에 따라
판정 모드를 나눈다:

  zscore       표본 충분 — 로버스트 z-score로 정식 판정
  provisional  표본 부족 — 중앙값 대비 배수로 '잠정' 판정 (낮은 신뢰도)
  insufficient 비교 자체가 무의미 — 판정하지 않음

`confidence`(0-100)로 판정을 얼마나 믿을 수 있는지 함께 돌려주므로, 소비 측
(대시보드·AI 역설계)은 잠정 판정을 그에 맞게 다룰 수 있다.
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

# 콜드스타트 임계값
MIN_SAMPLES_ZSCORE = 8      # 이 이상이면 z-score 정식 판정
MIN_SAMPLES_COMPARE = 3     # 이 미만이면 비교 자체를 하지 않음
PROVISIONAL_RATIO = 2.0     # 잠정 모드: 중앙값 대비 이 배수 이상이면 잠정 브레이크아웃
_CONFIDENT_SAMPLES = 30     # 이 정도 표본이면 신뢰도 100

MODE_ZSCORE = "zscore"
MODE_PROVISIONAL = "provisional"
MODE_INSUFFICIENT = "insufficient"


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
    # 콜드스타트 대응 — 이 판정을 얼마나 믿을 수 있는가
    mode: str = MODE_ZSCORE         # zscore | provisional | insufficient
    confidence: int = 0             # 0-100 (표본 수에 따라 상승)
    sample_size: int = 0            # 판정에 쓰인 동일 플랫폼 게시물 수
    ratios: dict[str, float] = field(default_factory=dict)  # 지표별 중앙값 대비 배수

    @property
    def is_provisional(self) -> bool:
        """표본 부족으로 내려진 잠정 판정인가."""
        return self.mode == MODE_PROVISIONAL


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


def detection_mode(sample_size: int, min_samples: int = MIN_SAMPLES_ZSCORE) -> str:
    """표본 수로 판정 모드 결정."""
    if sample_size < MIN_SAMPLES_COMPARE:
        return MODE_INSUFFICIENT
    if sample_size < min_samples:
        return MODE_PROVISIONAL
    return MODE_ZSCORE


def confidence_for(sample_size: int, min_samples: int = MIN_SAMPLES_ZSCORE) -> int:
    """판정 신뢰도(0-100). 표본이 많을수록 상승."""
    mode = detection_mode(sample_size, min_samples)
    if mode == MODE_INSUFFICIENT:
        return 0
    if mode == MODE_PROVISIONAL:
        span = max(1, min_samples - MIN_SAMPLES_COMPARE)
        progress = (sample_size - MIN_SAMPLES_COMPARE) / span
        return int(20 + progress * 25)          # 20~45
    span = max(1, _CONFIDENT_SAMPLES - min_samples)
    progress = min(1.0, (sample_size - min_samples) / span)
    return int(60 + progress * 40)              # 60~100


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
    min_samples: int = MIN_SAMPLES_ZSCORE,
    provisional_ratio: float = PROVISIONAL_RATIO,
) -> list[BreakoutResult]:
    """동일 계정/플랫폼 게시물 집합에 대해 브레이크아웃 판정.

    표본이 `min_samples` 미만이면 z-score 대신 중앙값 대비 배수로 잠정 판정하고,
    `MIN_SAMPLES_COMPARE` 미만이면 아예 판정하지 않는다(모두 is_breakout=False).
    반환은 breakout_score 내림차순.
    """
    sample_size = len(items)
    mode = detection_mode(sample_size, min_samples)
    confidence = confidence_for(sample_size, min_samples)
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
        if mode == MODE_ZSCORE:
            result = _judge_by_zscore(it, rates, baselines, z_threshold, z_clamp)
        elif mode == MODE_PROVISIONAL:
            result = _judge_provisionally(it, rates, baselines, provisional_ratio)
        else:
            result = BreakoutResult(
                post_id=it.post_id,
                breakout_score=0.0,
                is_breakout=False,
                rates={k: round(v, 4) for k, v in rates.items()},
            )
        result.mode = mode
        result.confidence = confidence
        result.sample_size = sample_size
        results.append(result)

    results.sort(key=lambda r: r.breakout_score, reverse=True)
    return results


def _judge_by_zscore(
    item: MetricInput,
    rates: dict[str, float],
    baselines: dict[str, tuple[float, float]],
    z_threshold: float,
    z_clamp: float,
) -> BreakoutResult:
    """표본이 충분할 때의 정식 판정 — 로버스트 z-score."""
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
    return BreakoutResult(
        post_id=item.post_id,
        breakout_score=score,
        is_breakout=weighted_z >= z_threshold,
        rates={k: round(v, 4) for k, v in rates.items()},
        z_scores=z_scores,
        reasons=reasons,
    )


def _judge_provisionally(
    item: MetricInput,
    rates: dict[str, float],
    baselines: dict[str, tuple[float, float]],
    provisional_ratio: float,
) -> BreakoutResult:
    """표본이 적을 때의 잠정 판정 — 중앙값 대비 배수.

    z-score는 분산 추정이 필요해 표본 3~7개에서는 신뢰할 수 없다. 대신 '다른
    게시물들의 중앙값보다 몇 배 잘 됐나'라는, 표본이 적어도 해석 가능한 신호를 쓴다.
    """
    ratios: dict[str, float] = {}
    weight_sum = 0.0
    weighted_ratio = 0.0
    for metric, weight in WEIGHTS.items():
        if metric not in rates or metric not in baselines:
            continue
        med, _scale = baselines[metric]
        if med <= 0:
            continue
        ratio = rates[metric] / med
        ratios[metric] = round(ratio, 3)
        weight_sum += weight
        weighted_ratio += weight * ratio

    composite = weighted_ratio / weight_sum if weight_sum else 0.0
    # 임계 배수에 도달하면 50점, 그 두 배면 100점
    span = max(0.1, provisional_ratio - 1.0)
    score = round(min(100.0, max(0.0, (composite - 1.0) / span * 50.0)), 1)
    reasons = sorted(
        (m for m, r in ratios.items() if r >= provisional_ratio),
        key=lambda m: ratios[m],
        reverse=True,
    )
    return BreakoutResult(
        post_id=item.post_id,
        breakout_score=score,
        is_breakout=composite >= provisional_ratio,
        rates={k: round(v, 4) for k, v in rates.items()},
        reasons=reasons,
        ratios=ratios,
    )
