"""브레이크아웃 탐지 서비스 — 저장된 지표를 조립해 판정 결과를 낸다."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from ..config.settings import Settings
from ..db import AccountMetricsRepository, MetricsRepository, PostRepository
from ..models import Post
from ..models.enums import Platform, PostStatus
from ..utils.time import now_utc
from .breakout import BreakoutResult, MetricInput, detect_breakouts

logger = logging.getLogger("branding.analysis")


@dataclass
class BreakoutRow:
    result: BreakoutResult
    post: Post


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
        self, weeks: int = 8, z_threshold: float = 2.5
    ) -> list[BreakoutRow]:
        """발행 게시물의 브레이크아웃을 플랫폼별로 판정. score 내림차순."""
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
            for result in detect_breakouts(inputs, z_threshold=z_threshold):
                rows.append(BreakoutRow(result=result, post=posts_by_id[result.post_id]))

        rows.sort(key=lambda r: r.result.breakout_score, reverse=True)
        return rows

    def breakouts_only(self, weeks: int = 8, z_threshold: float = 2.5) -> list[BreakoutRow]:
        return [r for r in self.analyze(weeks, z_threshold) if r.result.is_breakout]
