"""업로드 오케스트레이션 — 렌더된 슬라이드를 공개 URL로 만든다.

`slide.image_path`(로컬) → 업로드 → `slide.image_url`(공개). 이 단계가 끝나야
Instagram 발행이 가능하다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..config.settings import Settings
from ..db import PostRepository
from ..models import Post
from .base import Uploader, UploadError, slide_key

logger = logging.getLogger("branding.upload")


@dataclass
class UploadedSlide:
    index: int
    url: str
    skipped: bool = False   # 이미 URL이 있어 건너뜀


class UploadService:
    def __init__(
        self,
        settings: Settings,
        uploader: Uploader,
        post_repo: Optional[PostRepository] = None,
    ):
        self.settings = settings
        self.uploader = uploader
        self.post_repo = post_repo or PostRepository(settings.db_path)

    def upload_post(
        self, post: Post, force: bool = False, save: bool = True
    ) -> list[UploadedSlide]:
        """게시물의 렌더된 슬라이드를 모두 업로드하고 image_url을 채운다.

        `force=False`면 이미 URL이 있는 슬라이드는 건너뛴다(재업로드 비용 절약).
        """
        slides = post.content.ordered_slides()
        if not slides:
            raise ValueError(
                f"게시물 #{post.id}에 캐러셀 슬라이드가 없습니다."
            )

        unrendered = [s.index for s in slides if not s.image_path]
        if unrendered:
            raise ValueError(
                f"아직 렌더링되지 않은 슬라이드가 있습니다: {unrendered}. "
                f"branding render slides {post.id} 를 먼저 실행하세요."
            )

        self.uploader.check()
        results: list[UploadedSlide] = []
        for slide in slides:
            if slide.image_url and not force:
                results.append(UploadedSlide(slide.index, slide.image_url, skipped=True))
                continue
            key = slide_key(post.id, slide.index, prefix=self.settings.upload_prefix)
            result = self.uploader.upload(slide.image_path, key)
            slide.image_url = result.url
            results.append(UploadedSlide(slide.index, result.url))
            logger.info("슬라이드 %d 업로드 완료 → %s", slide.index, result.url)

        if save and post.id is not None:
            self.post_repo.save(post)
        return results

    def upload_by_id(self, post_id: int, force: bool = False) -> list[UploadedSlide]:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise ValueError(f"게시물 #{post_id}를 찾을 수 없습니다.")
        return self.upload_post(post, force=force)
