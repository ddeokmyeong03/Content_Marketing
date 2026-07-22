from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field

from .enums import PostStatus, Platform, MediaType, ContentPillar


class ImageBrief(BaseModel):
    description: str
    style_notes: str
    text_overlay: Optional[str] = None
    color_hints: list[str] = Field(default_factory=list)
    midjourney_prompt: str
    dall_e_prompt: str


class PostContent(BaseModel):
    caption_ko: str
    caption_en: Optional[str] = None
    hooks: list[str] = Field(default_factory=list)
    cta: str
    hashtags_ko: list[str] = Field(default_factory=list)
    hashtags_en: list[str] = Field(default_factory=list)
    image_brief: Optional[ImageBrief] = None


class Post(BaseModel):
    id: Optional[int] = None
    platform: Platform
    media_type: MediaType
    content_pillar: ContentPillar
    topic: str
    content: PostContent
    status: PostStatus = PostStatus.DRAFT
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    meta_post_id: Optional[str] = None
    permalink: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    week_number: int = Field(default=0)
    plan_id: Optional[int] = None

    def full_caption_ko(self) -> str:
        """해시태그 포함 최종 한국어 캡션 반환"""
        hashtags = " ".join(
            f"#{t}" if not t.startswith("#") else t
            for t in self.content.hashtags_ko + self.content.hashtags_en
        )
        parts = [self.content.caption_ko]
        if self.content.cta:
            parts.append(f"\n{self.content.cta}")
        if hashtags:
            parts.append(f"\n\n{hashtags}")
        return "\n".join(parts)


class ContentPlanTopic(BaseModel):
    pillar: ContentPillar
    topic: str
    platform: Platform
    day_offset: int          # 0=월요일, 6=일요일
    media_type: MediaType = MediaType.IMAGE


class ContentPlan(BaseModel):
    id: Optional[int] = None
    week_start: date
    week_end: date
    theme: str
    theme_ko: str
    topics: list[ContentPlanTopic] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "active"
