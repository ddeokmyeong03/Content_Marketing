"""발행 오케스트레이션: 플랫폼 라우팅 + 상태 전이 + 로깅."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from ..config.settings import Settings
from ..db import PostRepository, TokenRepository
from ..models import Post, PostStatus
from ..models.enums import Platform
from ..notify import Notifier, get_notifier
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
    will_retry: bool = False        # 일시 장애로 재시도가 예약되었는가
    attempts: int = 0               # 지금까지의 총 시도 횟수


class PublishService:
    def __init__(
        self,
        settings: Settings,
        post_repo: Optional[PostRepository] = None,
        token_repo: Optional[TokenRepository] = None,
        notifier: Optional[Notifier] = None,
    ):
        self.settings = settings
        self.post_repo = post_repo or PostRepository(settings.db_path)
        self.token_repo = token_repo or TokenRepository(settings.db_path)
        self.notifier = notifier or get_notifier(settings)

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
                        poll_interval_seconds=self.settings.ig_poll_interval_seconds,
                        poll_max_attempts=self.settings.ig_poll_max_attempts,
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
            return self._handle_failure(post, e)

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
            self.post_repo.clear_publish_retry(post.id)
        logger.info("발행 성공 (post #%s → %s)", post.id, primary.meta_post_id if primary else "?")
        link = primary.permalink if primary and primary.permalink else post.topic[:40]
        # 골든아워: 발행 직후 초기 참여가 알고리즘 도달을 좌우한다
        self.notifier.success(
            f"발행 완료 #{post.id} ({post.platform.value})",
            f"{link}\n⏱ 지금부터 {self.settings.golden_hour_minutes}분이 골든아워입니다 — "
            f"댓글 응대와 계정 활동으로 초기 참여를 올리세요.",
        )
        return PublishOutcome(post_id=post.id, success=True, result=primary)

    def _retry_delay_minutes(self, attempts: int) -> int:
        """지수 백오프 — 5 → 10 → 20 … (상한까지)."""
        base = max(1, self.settings.publish_retry_backoff_minutes)
        delay = base * (2 ** max(0, attempts - 1))
        return min(delay, max(base, self.settings.publish_retry_max_minutes))

    def _handle_failure(self, post: Post, error: MetaAPIError) -> PublishOutcome:
        """발행 실패 처리.

        일시 장애(레이트 리밋·5xx·네트워크)면 다음 재시도 시각을 예약해
        스케줄러가 다시 집어가게 하고, 그 외(토큰·권한·입력 오류)나 시도 횟수를
        모두 소진한 경우에는 영구 실패로 확정한다.
        """
        attempts = (post.publish_attempts or 0) + 1
        exhausted = attempts >= self.settings.publish_max_attempts
        will_retry = bool(error.retryable) and not exhausted

        next_retry_at = (
            now_utc() + timedelta(minutes=self._retry_delay_minutes(attempts))
            if will_retry
            else None
        )

        logger.warning(
            "발행 실패 (post #%s, 시도 %d/%d, 재시도=%s): %s",
            post.id,
            attempts,
            self.settings.publish_max_attempts,
            will_retry,
            error,
        )

        if post.id is not None:
            self.post_repo.mark_publish_failure(
                post.id,
                error_msg=str(error),
                attempts=attempts,
                next_retry_at=next_retry_at,
            )
            self.post_repo.log_publish_attempt(post.id, success=False, error_msg=str(error))

        if will_retry:
            self.notifier.warning(
                f"발행 실패 — 재시도 예정 #{post.id} ({post.platform.value})",
                f"{post.topic[:40]} — {error}\n"
                f"시도 {attempts}/{self.settings.publish_max_attempts}, "
                f"다음 재시도 {next_retry_at:%Y-%m-%d %H:%M} UTC",
            )
        else:
            reason = "시도 횟수 소진" if exhausted else "재시도 불가 오류"
            self.notifier.error(
                f"발행 실패 #{post.id} ({post.platform.value})",
                f"{post.topic[:40]} — {error}\n{reason} (시도 {attempts}회). 수동 확인이 필요합니다.",
            )

        return PublishOutcome(
            post_id=post.id,
            success=False,
            error=str(error),
            will_retry=will_retry,
            attempts=attempts,
        )

    def run_pending(self) -> list[PublishOutcome]:
        """예약 시간이 지난 승인 게시물을 모두 발행."""
        pending = self.post_repo.list_pending_publish()
        outcomes = [self.publish_post(p) for p in pending]
        if outcomes:
            ok = sum(1 for o in outcomes if o.success)
            retrying = sum(1 for o in outcomes if o.will_retry)
            logger.info(
                "발행 배치 완료: 성공 %d / 총 %d (재시도 예약 %d)", ok, len(outcomes), retrying
            )
        return outcomes
