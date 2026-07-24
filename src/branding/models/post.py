from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field

from .enums import PostStatus, Platform, MediaType, ContentPillar
from ..utils.time import now_utc


class ImageBrief(BaseModel):
    description: str
    style_notes: str
    text_overlay: Optional[str] = None
    color_hints: list[str] = Field(default_factory=list)
    midjourney_prompt: str
    dall_e_prompt: str


class HookVariant(BaseModel):
    """훅(첫 문장) 후보 — 사용된 심리 기법과 자기예측 점수 포함."""
    text: str
    technique: str = ""            # 예: curiosity_gap, contrarian_hook
    predicted_score: int = 0       # 모델 자기예측 참여 점수 (0-100)


class PostContent(BaseModel):
    caption_ko: str
    caption_en: Optional[str] = None
    hooks: list[str] = Field(default_factory=list)  # 훅 텍스트 (표시/호환용)
    cta: str
    hashtags_ko: list[str] = Field(default_factory=list)
    hashtags_en: list[str] = Field(default_factory=list)
    image_brief: Optional[ImageBrief] = None
    # 실제 발행에 사용할 공개 이미지 URL (Instagram 단일/카루셀). 이미지 생성·호스팅 후 채워짐.
    image_urls: list[str] = Field(default_factory=list)
    # 참여 엔진 산출물
    hook_variants: list[HookVariant] = Field(default_factory=list)
    chosen_hook: Optional[str] = None          # 캡션 첫 줄로 채택된 훅
    engagement_score: Optional[int] = None      # 최종 캡션 예측 참여 점수 (0-100)
    engagement_notes: Optional[str] = None      # 개선 코멘트/평가 근거


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
    created_at: datetime = Field(default_factory=now_utc)
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


class PostMetric(BaseModel):
    """발행된 게시물의 실제 성과 스냅샷 (Graph API 인사이트)."""
    post_id: int
    platform: Platform
    likes: int = 0
    comments: int = 0
    shares: int = 0
    saved: int = 0
    reach: int = 0
    views: int = 0
    profile_visits: int = 0        # 게시물에서 발생한 프로필 방문 (성장 신호)
    follows: int = 0               # 게시물에서 발생한 팔로우 (IG)
    total_interactions: int = 0    # 총 상호작용
    engagement_rate: float = 0.0
    fetched_at: datetime = Field(default_factory=now_utc)
    raw: dict = Field(default_factory=dict)

    def compute_engagement_rate(self) -> float:
        """(좋아요+댓글+공유+저장) / 도달. 도달 없으면 조회수로 대체."""
        interactions = self.total_interactions or (
            self.likes + self.comments + self.shares + self.saved
        )
        denom = self.reach or self.views
        return round(interactions / denom, 4) if denom else 0.0


class AccountMetric(BaseModel):
    """계정 단위 성과 스냅샷 — 팔로워 성장·도달 시계열(브레이크아웃 귀인의 기반)."""
    platform: Platform
    followers_count: int = 0
    reach: int = 0
    profile_views: int = 0
    views: int = 0
    fetched_at: datetime = Field(default_factory=now_utc)
    raw: dict = Field(default_factory=dict)


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
    generated_at: datetime = Field(default_factory=now_utc)
    status: str = "active"
