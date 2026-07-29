"""발행 오케스트레이션: 플랫폼 라우팅 + 상태 전이 + 로깅."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Optional

from ..config.settings import Settings
from ..db import PostRepository, TokenRepository
from ..models import Post, PostPublication, PostStatus
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
    # platform=both 의 부분 성공을 드러낸다 — 어디까지 올라갔고 무엇이 남았는가
    published: list[Platform] = field(default_factory=list)   # 이번에 새로 발행한 플랫폼
    skipped: list[Platform] = field(default_factory=list)     # 이미 발행돼 건너뛴 플랫폼


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

    def _targets(self, platform: Platform) -> list[Platform]:
        """발행해야 할 실제 플랫폼 목록. BOTH는 두 곳 모두."""
        if platform == Platform.BOTH:
            return [Platform.INSTAGRAM, Platform.THREADS]
        return [platform]

    def _publisher_for(self, platform: Platform):
        if platform == Platform.THREADS:
            return ThreadsPublisher(
                access_token=self._token(platform),
                user_id=self.settings.meta_threads_user_id,
                base=self.settings.threads_graph_base,
                publish_delay_seconds=self.settings.threads_publish_delay_seconds,
            )
        if platform == Platform.INSTAGRAM:
            return InstagramPublisher(
                access_token=self._token(platform),
                user_id=self.settings.meta_ig_user_id,
                base=self.settings.meta_graph_base,
                version=self.settings.meta_graph_version,
                poll_interval_seconds=self.settings.ig_poll_interval_seconds,
                poll_max_attempts=self.settings.ig_poll_max_attempts,
            )
        raise MetaAPIError(f"발행할 수 없는 플랫폼입니다: {platform.value}")

    def publish_post(self, post: Post) -> PublishOutcome:
        """단일 게시물 발행. 상태 전이 및 publish_log 기록까지 처리.

        `platform=both` 는 두 플랫폼을 순서대로 호출하는데, 앞이 성공하고 뒤가 실패하면
        게시물 전체가 실패로 남는다. 성공한 플랫폼을 그때그때 기록해 두지 않으면
        재시도가 이미 올라간 쪽을 다시 올려 중복 게시가 된다. 그래서 한 곳이 끝날
        때마다 즉시 기록하고, 재시도는 아직 안 올라간 플랫폼만 집어간다.
        """
        if post.id is not None:
            self.post_repo.update_status(post.id, PostStatus.PUBLISHING)

        targets = self._targets(post.platform)
        already = self.post_repo.published_platforms(post.id) if post.id is not None else set()
        skipped = [t for t in targets if t in already]
        remaining = [t for t in targets if t not in already]
        if skipped:
            logger.info(
                "이미 발행된 플랫폼은 건너뜁니다 (post #%s): %s",
                post.id,
                ", ".join(t.value for t in skipped),
            )

        published: list[Platform] = []
        results: dict[Platform, PublishResult] = {}
        try:
            for target in remaining:
                res = self._publisher_for(target).publish(post)
                results[target] = res
                if post.id is not None:
                    # 다음 플랫폼을 건드리기 전에 확정 — 여기서 죽어도 사실은 남는다
                    self.post_repo.record_publication(
                        PostPublication(
                            post_id=post.id,
                            platform=target,
                            meta_post_id=res.meta_post_id,
                            permalink=res.permalink,
                            raw=res.raw,
                        )
                    )
                published.append(target)
        except MetaAPIError as e:
            return self._handle_failure(post, e, published=published, skipped=skipped)

        primary = self._primary_result(post, targets, results)

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
        return PublishOutcome(
            post_id=post.id, success=True, result=primary,
            published=published, skipped=skipped,
        )

    def _primary_result(
        self,
        post: Post,
        targets: list[Platform],
        results: dict[Platform, PublishResult],
    ) -> Optional[PublishResult]:
        """게시물 대표로 남길 결과 — 항상 첫 번째 대상 플랫폼 기준.

        이번 시도에서 올린 것과 앞선 시도에서 이미 올린 것을 함께 본다. 그러지 않으면
        부분 성공 후 재시도에서 대표 링크가 두 번째 플랫폼으로 뒤바뀐다.
        """
        stored: dict[Platform, PublishResult] = {}
        if post.id is not None:
            stored = {
                p.platform: PublishResult(
                    meta_post_id=p.meta_post_id or "", permalink=p.permalink, raw=p.raw
                )
                for p in self.post_repo.list_publications(post.id)
            }
        merged = {**stored, **results}
        for target in targets:
            if target in merged:
                return merged[target]
        return None

    def _retry_delay_minutes(self, attempts: int) -> int:
        """지수 백오프 — 5 → 10 → 20 … (상한까지)."""
        base = max(1, self.settings.publish_retry_backoff_minutes)
        delay = base * (2 ** max(0, attempts - 1))
        return min(delay, max(base, self.settings.publish_retry_max_minutes))

    def _handle_failure(
        self,
        post: Post,
        error: MetaAPIError,
        published: Optional[list[Platform]] = None,
        skipped: Optional[list[Platform]] = None,
    ) -> PublishOutcome:
        """발행 실패 처리.

        일시 장애(레이트 리밋·5xx·네트워크)면 다음 재시도 시각을 예약해
        스케줄러가 다시 집어가게 하고, 그 외(토큰·권한·입력 오류)나 시도 횟수를
        모두 소진한 경우에는 영구 실패로 확정한다.

        `published`/`skipped` 는 platform=both 의 부분 성공을 알리기 위한 것 —
        "인스타는 올라갔고 스레드만 실패"를 사람이 알아야 수동 대응이 가능하다.
        """
        published = published or []
        skipped = skipped or []
        done = skipped + published
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

        # 부분 성공은 반드시 알린다 — 한쪽만 올라간 상태를 모르면 수동으로 중복 게시한다
        partial = (
            f"\n이미 발행됨: {', '.join(p.value for p in done)} "
            f"(재시도는 나머지만 올립니다)"
            if done
            else ""
        )

        if will_retry:
            self.notifier.warning(
                f"발행 실패 — 재시도 예정 #{post.id} ({post.platform.value})",
                f"{post.topic[:40]} — {error}\n"
                f"시도 {attempts}/{self.settings.publish_max_attempts}, "
                f"다음 재시도 {next_retry_at:%Y-%m-%d %H:%M} UTC{partial}",
            )
        else:
            reason = "시도 횟수 소진" if exhausted else "재시도 불가 오류"
            self.notifier.error(
                f"발행 실패 #{post.id} ({post.platform.value})",
                f"{post.topic[:40]} — {error}\n{reason} (시도 {attempts}회). "
                f"수동 확인이 필요합니다.{partial}",
            )

        return PublishOutcome(
            post_id=post.id,
            success=False,
            error=str(error),
            will_retry=will_retry,
            attempts=attempts,
            published=published,
            skipped=skipped,
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
