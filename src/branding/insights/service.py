"""발행 성과(인사이트) 수집 — 측정→피드백 루프의 입력.

발행된 게시물의 실제 지표를 Graph API로 가져와 post_metrics에 스냅샷으로 저장한다.
저장된 데이터는 MetricsRepository.top_performers 를 통해 다음 기획에 재주입된다.

- Instagram: /{media}?fields=like_count,comments_count + /{media}/insights?metric=reach,saved,shares
- Threads:   /{media}/insights?metric=likes,replies,reposts,quotes,views
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from ..config.settings import Settings
from ..db import MetricsRepository, PostRepository, TokenRepository
from ..models import Post, PostMetric
from ..models.enums import Platform, PostStatus
from ..publisher.base import GraphHTTP, MetaAPIError
from ..utils.time import now_utc

logger = logging.getLogger("branding.insights")


def parse_insights(payload: dict) -> dict[str, int]:
    """Graph insights 응답을 {metric_name: value} 로 정규화.

    values[0].value 또는 total_value.value 두 형태 모두 처리.
    """
    out: dict[str, int] = {}
    for item in payload.get("data", []):
        name = item.get("name")
        if not name:
            continue
        value = 0
        if isinstance(item.get("values"), list) and item["values"]:
            value = item["values"][0].get("value", 0)
        elif isinstance(item.get("total_value"), dict):
            value = item["total_value"].get("value", 0)
        out[name] = int(value or 0)
    return out


class InsightsService:
    def __init__(
        self,
        settings: Settings,
        post_repo: Optional[PostRepository] = None,
        metrics_repo: Optional[MetricsRepository] = None,
        token_repo: Optional[TokenRepository] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.post_repo = post_repo or PostRepository(settings.db_path)
        self.metrics_repo = metrics_repo or MetricsRepository(settings.db_path)
        self.token_repo = token_repo or TokenRepository(settings.db_path)
        self._transport = transport

    def _token(self, platform: Platform) -> str:
        return self.token_repo.get_token(platform.value) or self.settings.meta_access_token

    def _http(self, platform: Platform) -> GraphHTTP:
        if platform == Platform.THREADS:
            return GraphHTTP(self.settings.threads_graph_base, "v1.0", transport=self._transport)
        return GraphHTTP(
            self.settings.meta_graph_base,
            self.settings.meta_graph_version,
            transport=self._transport,
        )

    def fetch_post(self, post: Post) -> PostMetric:
        if not post.meta_post_id:
            raise MetaAPIError(f"게시물 #{post.id}에 meta_post_id가 없습니다.")
        token = self._token(post.platform)
        http = self._http(post.platform)
        media_id = post.meta_post_id

        if post.platform == Platform.THREADS:
            ins = parse_insights(
                http.get(
                    f"{media_id}/insights",
                    {"metric": "likes,replies,reposts,quotes,views", "access_token": token},
                )
            )
            metric = PostMetric(
                post_id=post.id,
                platform=post.platform,
                likes=ins.get("likes", 0),
                comments=ins.get("replies", 0),
                shares=ins.get("reposts", 0) + ins.get("quotes", 0),
                views=ins.get("views", 0),
                raw=ins,
            )
        else:  # Instagram
            fields = http.get(
                media_id, {"fields": "like_count,comments_count", "access_token": token}
            )
            ins = parse_insights(
                http.get(
                    f"{media_id}/insights",
                    {"metric": "reach,saved,shares", "access_token": token},
                )
            )
            metric = PostMetric(
                post_id=post.id,
                platform=post.platform,
                likes=int(fields.get("like_count", 0) or 0),
                comments=int(fields.get("comments_count", 0) or 0),
                shares=ins.get("shares", 0),
                saved=ins.get("saved", 0),
                reach=ins.get("reach", 0),
                raw={**fields, **ins},
            )

        metric.engagement_rate = metric.compute_engagement_rate()
        return metric

    def sync(self) -> list[PostMetric]:
        """발행된 모든 게시물의 최신 성과를 수집·저장."""
        published = [
            p for p in self.post_repo.list_by_status(PostStatus.PUBLISHED) if p.meta_post_id
        ]
        collected: list[PostMetric] = []
        for post in published:
            try:
                metric = self.fetch_post(post)
                self.metrics_repo.save_snapshot(metric)
                collected.append(metric)
            except MetaAPIError as e:
                logger.warning("인사이트 수집 실패 (post #%s): %s", post.id, e)
        if collected:
            logger.info("인사이트 수집 완료: %d개 게시물", len(collected))
        return collected
