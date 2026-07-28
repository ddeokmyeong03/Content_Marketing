"""브레이크아웃 탐지 서비스 — 저장된 지표를 조립해 판정 결과를 낸다."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from ..config.brand_config import BrandConfig
from ..config.settings import Settings
from ..db import (
    AccountMetricsRepository, BreakoutPatternRepository, MetricsRepository, PostRepository,
)
from ..models import BreakoutPattern, Post
from ..models.enums import Platform, PostStatus
from ..utils.time import now_utc
from .attribution import AttributionResult, PostAttrInput, attribute
from .breakout import (
    MIN_SAMPLES_ZSCORE,
    PROVISIONAL_RATIO,
    BreakoutResult,
    MetricInput,
    confidence_for,
    detect_breakouts,
    detection_mode,
)

logger = logging.getLogger("branding.analysis")


@dataclass
class BreakoutRow:
    result: BreakoutResult
    post: Post


@dataclass
class AttributionRow:
    result: AttributionResult
    post: Post


@dataclass
class DetectionCoverage:
    """플랫폼별 판정 가능 여부 진단."""
    platform: Platform
    sample_size: int
    mode: str                 # zscore | provisional | insufficient
    confidence: int           # 0-100
    needed_for_zscore: int    # 정식 판정까지 더 필요한 게시물 수 (0 = 이미 가능)


@dataclass
class PlatformAttribution:
    platform: Platform
    follower_growth: Optional[int]   # None = 스냅샷 부족
    rows: list[AttributionRow]


class BreakoutService:
    def __init__(
        self,
        settings: Settings,
        post_repo: Optional[PostRepository] = None,
        metrics_repo: Optional[MetricsRepository] = None,
        account_repo: Optional[AccountMetricsRepository] = None,
    ):
        self.settings = settings
        self.post_repo = post_repo or PostRepository(settings.db_path)
        self.metrics_repo = metrics_repo or MetricsRepository(settings.db_path)
        self.account_repo = account_repo or AccountMetricsRepository(settings.db_path)

    def analyze(
        self,
        weeks: int = 8,
        z_threshold: float = 2.5,
        min_samples: int = MIN_SAMPLES_ZSCORE,
        provisional_ratio: float = PROVISIONAL_RATIO,
    ) -> list[BreakoutRow]:
        """발행 게시물의 브레이크아웃을 플랫폼별로 판정. score 내림차순.

        표본이 `min_samples` 미만인 플랫폼은 잠정 판정 모드로 내려간다
        (결과의 `mode`·`confidence` 참조).
        """
        since = now_utc() - timedelta(weeks=weeks)
        published = [
            p
            for p in self.post_repo.list_by_status(PostStatus.PUBLISHED)
            if p.meta_post_id and (p.published_at is None or p.published_at >= since)
        ]
        posts_by_id = {p.id: p for p in published}

        # 플랫폼별로 분포를 따로 계산해야 정규화가 유효
        by_platform: dict[Platform, list[MetricInput]] = {}
        for post in published:
            metric = self.metrics_repo.latest_for_post(post.id)
            if metric is None:
                continue
            followers = (
                self.account_repo.followers_at(post.platform, post.published_at)
                if post.published_at
                else self.account_repo.latest(post.platform)
                and self.account_repo.latest(post.platform).followers_count
            )
            by_platform.setdefault(post.platform, []).append(
                MetricInput(
                    post_id=post.id,
                    reach=metric.reach,
                    shares=metric.shares,
                    saved=metric.saved,
                    follows=metric.follows,
                    total_interactions=metric.total_interactions,
                    likes=metric.likes,
                    comments=metric.comments,
                    followers_at_post=followers,
                )
            )

        rows: list[BreakoutRow] = []
        for platform, inputs in by_platform.items():
            detected = detect_breakouts(
                inputs,
                z_threshold=z_threshold,
                min_samples=min_samples,
                provisional_ratio=provisional_ratio,
            )
            for result in detected:
                rows.append(BreakoutRow(result=result, post=posts_by_id[result.post_id]))

        rows.sort(key=lambda r: r.result.breakout_score, reverse=True)
        return rows

    def breakouts_only(
        self,
        weeks: int = 8,
        z_threshold: float = 2.5,
        min_samples: int = MIN_SAMPLES_ZSCORE,
        provisional_ratio: float = PROVISIONAL_RATIO,
        include_provisional: bool = True,
    ) -> list[BreakoutRow]:
        """브레이크아웃만 추림.

        `include_provisional=False` 면 표본 부족으로 내려진 잠정 판정은 제외한다
        (AI 역설계처럼 비용이 드는 소비자용).
        """
        rows = [
            r
            for r in self.analyze(weeks, z_threshold, min_samples, provisional_ratio)
            if r.result.is_breakout
        ]
        if not include_provisional:
            rows = [r for r in rows if not r.result.is_provisional]
        return rows

    def coverage(
        self, weeks: int = 8, min_samples: int = MIN_SAMPLES_ZSCORE
    ) -> list[DetectionCoverage]:
        """플랫폼별 판정 가능 여부 — '왜 브레이크아웃이 안 나오는가'에 답한다.

        신규 계정에서 결과가 비는 것이 '터진 게시물이 없어서'인지 '표본이 부족해
        판정을 못 해서'인지 구분하기 위한 진단용.
        """
        counts: dict[Platform, int] = {}
        for row in self.analyze(weeks=weeks, min_samples=min_samples):
            counts[row.post.platform] = row.result.sample_size

        return [
            DetectionCoverage(
                platform=platform,
                sample_size=size,
                mode=detection_mode(size, min_samples),
                confidence=confidence_for(size, min_samples),
                needed_for_zscore=max(0, min_samples - size),
            )
            for platform, size in sorted(counts.items(), key=lambda kv: kv[0].value)
        ]

    def attribute_growth(self, days: int = 30) -> list[PlatformAttribution]:
        """기간 내 계정 팔로워 순증가를 게시물에 귀속 (플랫폼별)."""
        since = now_utc() - timedelta(days=days)
        published = [
            p
            for p in self.post_repo.list_by_status(PostStatus.PUBLISHED)
            if p.meta_post_id and p.published_at and p.published_at >= since
        ]
        posts_by_id = {p.id: p for p in published}

        by_platform: dict[Platform, list[PostAttrInput]] = {}
        for post in published:
            metric = self.metrics_repo.latest_for_post(post.id)
            if metric is None:
                continue
            interactions = metric.total_interactions or (
                metric.likes + metric.comments + metric.shares + metric.saved
            )
            by_platform.setdefault(post.platform, []).append(
                PostAttrInput(post_id=post.id, follows=metric.follows, interactions=interactions)
            )

        out: list[PlatformAttribution] = []
        for platform, inputs in by_platform.items():
            growth = self.account_repo.follower_growth(platform, days=days)
            results = attribute(inputs, growth or 0)
            rows = [AttributionRow(result=r, post=posts_by_id[r.post_id]) for r in results]
            out.append(PlatformAttribution(platform=platform, follower_growth=growth, rows=rows))
        return out

    def deconstruct_new(
        self,
        brand: BrandConfig,
        api_key: str,
        weeks: int = 8,
        z_threshold: Optional[float] = None,
        model: str = "claude-opus-4-8",
        limit: Optional[int] = None,
        skip_existing: bool = True,
        include_provisional: bool = False,
    ) -> list[BreakoutPattern]:
        """탐지된 브레이크아웃을 AI로 역설계해 승리 공식으로 저장.

        이미 분석된 게시물은 기본적으로 건너뛴다(중복 방지·비용 절약).
        표본 부족으로 내려진 잠정 판정은 기본적으로 제외한다 — 통계적으로 약한
        신호에 AI 비용을 쓰지 않기 위함이며, `include_provisional=True`로 포함할 수 있다.
        """
        from ..ai.deconstruct import deconstruct_breakout  # 지연 임포트(무거운 ai 패키지)

        pattern_repo = BreakoutPatternRepository(self.settings.db_path)
        rows = self.breakouts_only(
            weeks,
            z_threshold if z_threshold is not None else brand.analysis.z_threshold,
            min_samples=brand.analysis.min_samples,
            provisional_ratio=brand.analysis.provisional_ratio,
            include_provisional=include_provisional,
        )
        if limit is not None:
            rows = rows[:limit]

        saved: list[BreakoutPattern] = []
        for row in rows:
            if skip_existing and pattern_repo.exists_for_post(row.post.id):
                continue
            metric = self.metrics_repo.latest_for_post(row.post.id)
            snapshot = {
                "reach": metric.reach if metric else 0,
                "likes": metric.likes if metric else 0,
                "comments": metric.comments if metric else 0,
                "shares": metric.shares if metric else 0,
                "saved": metric.saved if metric else 0,
                "follows": metric.follows if metric else 0,
            }
            pattern = deconstruct_breakout(
                brand_config=brand,
                api_key=api_key,
                post=row.post,
                breakout_score=row.result.breakout_score,
                reasons=row.result.reasons,
                metrics_snapshot=snapshot,
                platform=row.post.platform,
                model=model,
            )
            saved.append(pattern_repo.save(pattern))
        return saved
