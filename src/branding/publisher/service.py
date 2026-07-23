"""발행 오케스트레이션: 플랫폼 라우팅 + 상태 전이 + 로깅."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..config.settings import Settings
from ..db import PostRepository, TokenRepository
from ..models import Post, PostStatus
from ..models.enums import Platform
from ..utils.time import now_utc
from .base import MetaAPIError, PublishResult
from .instagram import InstagramPublisher
from .threads import ThreadsPublisher

logger = logging.getLogger("branding.publisher")


@dataclass
class PublishOutcome:
    post_id: Optional[int]
    success: bool
    result: Optional[PublishResult] = None
    error: Optional[str] = None


class PublishService:
    def __init__(
        self,
        settings: Settings,
        post_repo: Optional[PostRepository] = None,
        token_repo: Optional[TokenRepository] = None,
    ):
        self.settings = settings
        self.post_repo = post_repo or PostRepository(settings.db_path)
        self.token_repo = token_repo or TokenRepository(settings.db_path)

    # --- 토큰 해석: token_store 우선, 없으면 .env 값 ---
    def _token(self, platform: Platform) -> str:
        stored = self.token_repo.get_token(platform.value)
        return stored or self.settings.meta_access_token

    def _publishers(self, platform: Platform):
        """플랫폼별 퍼블리셔 목록. BOTH는 두 플랫폼 모두 발행."""
        targets = (
            [Platform.INSTAGRAM, Platform.THREADS]
            if platform == Platform.BOTH
            else [platform]
        )
        result = []
        for t in targets:
            if t == Platform.THREADS:
                result.append(
                    ThreadsPublisher(
                        access_token=self._token(t),
                        user_id=self.settings.meta_threads_user_id,
                        base=self.settings.threads_graph_base,
                        publish_delay_seconds=self.settings.threads_publish_delay_seconds,
                    )
                )
            elif t == Platform.INSTAGRAM:
                result.append(
                    InstagramPublisher(
                        access_token=self._token(t),
                        user_id=self.settings.meta_ig_user_id,
                        base=self.settings.meta_graph_base,
                        version=self.settings.meta_graph_version,
                        publish_delay_seconds=self.settings.threads_publish_delay_seconds,
                    )
                )
        return result

    def publish_post(self, post: Post) -> PublishOutcome:
        """단일 게시물 발행. 상태 전이 및 publish_log 기록까지 처리."""
        if post.id is not None:
            self.post_repo.update_status(post.id, PostStatus.PUBLISHING)

        try:
            publishers = self._publishers(post.platform)
            primary: Optional[PublishResult] = None
            for pub in publishers:
                res = pub.publish(post)
                primary = primary or res
        except MetaAPIError as e:
            logger.warning("발행 실패 (post #%s): %s", post.id, e)
            if post.id is not None:
                self.post_repo.update_status(post.id, PostStatus.FAILED)
                self.post_repo.log_publish_attempt(post.id, success=False, error_msg=str(e))
            return PublishOutcome(post_id=post.id, success=False, error=str(e))

        # 성공: 발행 메타데이터 기록
        updated = post.model_copy(
            update={
                "status": PostStatus.PUBLISHED,
                "published_at": now_utc(),
                "meta_post_id": primary.meta_post_id if primary else None,
                "permalink": primary.permalink if primary else None,
            }
        )
        self.post_repo.save(updated)
        if post.id is not None:
            self.post_repo.log_publish_attempt(
                post.id, success=True, response=primary.raw if primary else None
            )
        logger.info("발행 성공 (post #%s → %s)", post.id, primary.meta_post_id if primary else "?")
        return PublishOutcome(post_id=post.id, success=True, result=primary)

    def run_pending(self) -> list[PublishOutcome]:
        """예약 시간이 지난 승인 게시물을 모두 발행."""
        pending = self.post_repo.list_pending_publish()
        outcomes = [self.publish_post(p) for p in pending]
        if outcomes:
            ok = sum(1 for o in outcomes if o.success)
            logger.info("발행 배치 완료: 성공 %d / 총 %d", ok, len(outcomes))
        return outcomes
