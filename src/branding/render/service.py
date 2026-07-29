"""슬라이드 렌더링 오케스트레이션 — 게시물의 캐러셀을 PNG 세트로 굽는다.

렌더 결과는 `slide.image_path`(로컬 경로)에 기록된다. 발행에 필요한 공개 URL
(`slide.image_url`)은 업로드 단계에서 채워진다 — 렌더와 호스팅은 별개다.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config.brand_config import BrandConfig
from ..config.settings import Settings
from ..db import PostRepository
from ..models import Post
from .card import build_card_html
from .png import render_html_to_png

logger = logging.getLogger("branding.render")


@dataclass
class RenderedSlide:
    index: int
    path: Path
    headline: str
    oversized: bool          # 글자수 한도를 넘겨 폰트가 축소된 슬라이드


class SlideRenderer:
    def __init__(
        self,
        settings: Settings,
        brand: BrandConfig,
        post_repo: Optional[PostRepository] = None,
    ):
        self.settings = settings
        self.brand = brand
        self.post_repo = post_repo or PostRepository(settings.db_path)

    def output_dir(self, post_id: int) -> Path:
        return Path(self.settings.data_dir) / "renders" / f"post_{post_id}"

    def render_post(self, post: Post, save: bool = True) -> list[RenderedSlide]:
        """게시물의 슬라이드를 전부 PNG로 굽고 image_path를 채운다."""
        slides = post.content.ordered_slides()
        if not slides:
            raise ValueError(
                f"게시물 #{post.id}에 캐러셀 슬라이드가 없습니다. "
                "plan generate --captions 로 캐러셀 콘텐츠를 먼저 생성하세요."
            )

        cfg = self.brand.carousel
        out_dir = self.output_dir(post.id)
        rendered: list[RenderedSlide] = []

        for slide in slides:
            html = build_card_html(slide, self.brand, total=len(slides), carousel=cfg)
            path = out_dir / f"slide_{slide.index:02d}.png"
            render_html_to_png(html, path, width=cfg.width, height=cfg.height)
            slide.image_path = str(path)

            oversized = len(slide.headline) > cfg.headline_max_chars
            if oversized:
                logger.warning(
                    "슬라이드 %d 헤드라인이 한도를 넘겨 글씨가 작아집니다 (%d자 > %d자): %s",
                    slide.index, len(slide.headline), cfg.headline_max_chars, slide.headline,
                )
            rendered.append(
                RenderedSlide(
                    index=slide.index, path=path, headline=slide.headline, oversized=oversized
                )
            )

        if save and post.id is not None:
            self.post_repo.save(post)
        return rendered

    def render_by_id(self, post_id: int) -> list[RenderedSlide]:
        post = self.post_repo.get_by_id(post_id)
        if post is None:
            raise ValueError(f"게시물 #{post_id}를 찾을 수 없습니다.")
        return self.render_post(post)
