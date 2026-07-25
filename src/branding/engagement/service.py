"""댓글 수집 · 답글 응대 (계정 활성화).

알고리즘 도달에는 게시 자체보다 **참여율과 계정 활성도**가 크게 작용한다.
이 모듈은 공식 API로 가능한 범위 — 내 게시물의 댓글 읽기와 답글 달기 — 를 자동화한다.

- Instagram: GET /{media-id}/comments · POST /{comment-id}/replies  (instagram_manage_comments)
- Threads:   GET /{media-id}/replies  · POST /{user-id}/threads(reply_to_id) → /threads_publish
             (threads_manage_replies)

※ 타 계정 팔로우/좋아요는 공식 API에 엔드포인트가 없고 ToS 위반·계정 정지 위험이 있어
  자동화하지 않는다. 대신 타깃 발굴 후 사람이 실행하는 방식을 권장한다.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

import httpx

from ..config.brand_config import BrandConfig
from ..config.settings import Settings
from ..db import CommentRepository, PostRepository, TokenRepository
from ..models import Comment, Post
from ..models.enums import CommentStatus, Platform, PostStatus
from ..publisher.base import GraphHTTP, MetaAPIError
from ..utils.time import parse_dt

logger = logging.getLogger("branding.engagement")


@dataclass
class ReplyOutcome:
    comment_id: Optional[int]
    success: bool
    error: Optional[str] = None


class EngagementService:
    def __init__(
        self,
        settings: Settings,
        post_repo: Optional[PostRepository] = None,
        comment_repo: Optional[CommentRepository] = None,
        token_repo: Optional[TokenRepository] = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.settings = settings
        self.post_repo = post_repo or PostRepository(settings.db_path)
        self.comment_repo = comment_repo or CommentRepository(settings.db_path)
        self.token_repo = token_repo or TokenRepository(settings.db_path)
        self._transport = transport

    def _token(self, platform: Platform) -> str:
        return self.token_repo.get_token(platform.value) or self.settings.meta_access_token

    def _http(self, platform: Platform) -> GraphHTTP:
        if platform == Platform.THREADS:
            return GraphHTTP(self.settings.threads_graph_base, "v1.0", transport=self._transport)
        return GraphHTTP(
            self.settings.meta_graph_base, self.settings.meta_graph_version,
            transport=self._transport,
        )

    # --- 수집 ---

    def fetch_for_post(self, post: Post) -> list[Comment]:
        """게시물 한 건의 댓글/답글을 가져와 신규만 저장."""
        if not post.meta_post_id:
            return []
        token = self._token(post.platform)
        http = self._http(post.platform)
        path = "replies" if post.platform == Platform.THREADS else "comments"
        fields = ("id,text,username,timestamp"
                  if post.platform == Platform.THREADS else "id,text,username,timestamp")
        payload = http.get(
            f"{post.meta_post_id}/{path}", {"fields": fields, "access_token": token}
        )

        saved: list[Comment] = []
        for item in payload.get("data", []):
            ext_id = str(item.get("id", ""))
            if not ext_id or self.comment_repo.exists(ext_id):
                continue
            comment = Comment(
                post_id=post.id,
                platform=post.platform,
                external_id=ext_id,
                author=item.get("username", "") or "",
                text=item.get("text", "") or "",
                status=CommentStatus.NEW,
                commented_at=parse_dt(item.get("timestamp")),
            )
            saved.append(self.comment_repo.upsert(comment))
        return saved

    def sync_comments(self, limit_posts: int = 20) -> list[Comment]:
        """최근 발행 게시물들의 신규 댓글 수집."""
        published = [
            p for p in self.post_repo.list_by_status(PostStatus.PUBLISHED) if p.meta_post_id
        ][:limit_posts]
        collected: list[Comment] = []
        for post in published:
            try:
                collected.extend(self.fetch_for_post(post))
            except MetaAPIError as e:
                logger.warning("댓글 수집 실패 (post #%s): %s", post.id, e)
        if collected:
            logger.info("신규 댓글 %d건 수집", len(collected))
        return collected

    # --- 초안 ---

    def draft_replies(
        self, brand: BrandConfig, api_key: str, limit: int = 20,
        model: str = "claude-opus-4-8",
    ) -> list[Comment]:
        """NEW 댓글에 AI 답글 초안 생성. 스팸은 IGNORED 처리."""
        from ..ai.reply_gen import generate_reply  # 지연 임포트

        drafted: list[Comment] = []
        for c in self.comment_repo.list_by_status(CommentStatus.NEW)[:limit]:
            post = self.post_repo.get_by_id(c.post_id) if c.post_id else None
            try:
                draft = generate_reply(
                    brand_config=brand, api_key=api_key, comment_text=c.text,
                    author=c.author, platform=c.platform,
                    post_topic=post.topic if post else None,
                    post_caption=post.content.caption_ko if post else None,
                    model=model,
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("답글 초안 실패 (comment #%s): %s", c.id, e)
                continue
            if not draft.needs_reply:
                self.comment_repo.mark_status(c.id, CommentStatus.IGNORED)
                continue
            self.comment_repo.save_draft(c.id, draft.reply)
            drafted.append(c.model_copy(update={
                "draft_reply": draft.reply, "status": CommentStatus.DRAFTED,
            }))
        return drafted

    # --- 발행 ---

    def post_reply(self, comment: Comment, message: Optional[str] = None) -> ReplyOutcome:
        """답글 발행. message 미지정 시 저장된 초안 사용."""
        body = (message or comment.draft_reply or "").strip()
        if not body:
            return ReplyOutcome(comment.id, False, "답글 내용이 없습니다.")
        token = self._token(comment.platform)
        http = self._http(comment.platform)

        try:
            if comment.platform == Platform.THREADS:
                user_id = self.settings.meta_threads_user_id
                if not user_id:
                    raise MetaAPIError("META_THREADS_USER_ID가 없습니다.")
                created = http.post(
                    f"{user_id}/threads",
                    {
                        "media_type": "TEXT", "text": body,
                        "reply_to_id": comment.external_id, "access_token": token,
                    },
                )
                creation_id = created.get("id")
                if not creation_id:
                    raise MetaAPIError("답글 컨테이너 생성 실패", body=created)
                if self.settings.threads_publish_delay_seconds > 0:
                    time.sleep(self.settings.threads_publish_delay_seconds)
                published = http.post(
                    f"{user_id}/threads_publish",
                    {"creation_id": creation_id, "access_token": token},
                )
                reply_id = str(published.get("id", "")) or None
            else:  # Instagram
                published = http.post(
                    f"{comment.external_id}/replies",
                    {"message": body, "access_token": token},
                )
                reply_id = str(published.get("id", "")) or None
        except MetaAPIError as e:
            logger.warning("답글 발행 실패 (comment #%s): %s", comment.id, e)
            if comment.id:
                self.comment_repo.mark_status(comment.id, CommentStatus.FAILED, str(e))
            return ReplyOutcome(comment.id, False, str(e))

        if comment.id:
            self.comment_repo.mark_replied(comment.id, reply_id)
        logger.info("답글 발행 (comment #%s)", comment.id)
        return ReplyOutcome(comment.id, True)

    def reply_all_drafted(self, limit: int = 20) -> list[ReplyOutcome]:
        """초안이 준비된 댓글에 일괄 답글 (auto_approve 운영용)."""
        outs = []
        for c in self.comment_repo.list_by_status(CommentStatus.DRAFTED)[:limit]:
            outs.append(self.post_reply(c))
        return outs
