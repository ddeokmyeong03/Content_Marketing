from datetime import datetime, date
from typing import Optional
from pydantic import BaseModel, Field

from .enums import PostStatus, Platform, MediaType, ContentPillar, CommentStatus
from ..utils.time import now_utc


class ImageBrief(BaseModel):
    description: str
    style_notes: str
    text_overlay: Optional[str] = None
    color_hints: list[str] = Field(default_factory=list)
    midjourney_prompt: str
    dall_e_prompt: str


class CarouselSlide(BaseModel):
    """캐러셀 한 장의 구조.

    슬라이드별 문구·강조·역할을 데이터로 들고 있어야 템플릿 렌더링(HTML/CSS→PNG)으로
    글자 수와 레이아웃을 통제할 수 있다. `image_url`은 렌더링·업로드 후 채워진다.
    """
    index: int                                  # 1부터 시작하는 노출 순서
    role: str = "body"                          # hook | body | proof | cta
    headline: str = ""                          # 큰 글씨 (짧게)
    body: str = ""                              # 보조 문구
    emphasis: list[str] = Field(default_factory=list)  # 강조할 단어/구절
    image_brief: Optional[str] = None           # 이 슬라이드용 이미지 지시
    image_url: Optional[str] = None             # 렌더링·호스팅 후 채워지는 공개 URL


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
    # 캐러셀 슬라이드 구조 (있으면 발행 순서·이미지의 기준이 된다)
    slides: list[CarouselSlide] = Field(default_factory=list)
    # 참여 엔진 산출물
    hook_variants: list[HookVariant] = Field(default_factory=list)
    chosen_hook: Optional[str] = None          # 캡션 첫 줄로 채택된 훅
    engagement_score: Optional[int] = None      # 최종 캡션 예측 참여 점수 (0-100)
    engagement_notes: Optional[str] = None      # 개선 코멘트/평가 근거

    def ordered_slides(self) -> list["CarouselSlide"]:
        """노출 순서대로 정렬된 슬라이드."""
        return sorted(self.slides, key=lambda s: s.index)

    def publish_image_urls(self) -> list[str]:
        """발행에 사용할 공개 이미지 URL(순서대로).

        슬라이드 구조가 있으면 그 순서를 따르고, 없으면 기존 `image_urls`를 쓴다.
        """
        if self.slides:
            return [s.image_url for s in self.ordered_slides() if s.image_url]
        return list(self.image_urls)

    def missing_slide_images(self) -> list[int]:
        """이미지 URL이 아직 없는 슬라이드 번호 목록 (발행 전 점검용)."""
        return [s.index for s in self.ordered_slides() if not s.image_url]


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
    # 발행 재시도 상태 (PostRepository 전용 메서드가 갱신, save()는 건드리지 않음)
    publish_attempts: int = 0
    next_retry_at: Optional[datetime] = None   # None = 재시도 예정 없음(영구 실패/정상)
    last_error: Optional[str] = None

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


class Comment(BaseModel):
    """내 게시물에 달린 댓글/답글 + AI 답글 초안.

    계정 활성도(답글 응대)는 알고리즘 도달에 직접 영향을 준다.
    """
    id: Optional[int] = None
    post_id: Optional[int] = None
    platform: Platform
    external_id: str                     # 플랫폼 댓글 ID
    author: str = ""
    text: str = ""
    status: CommentStatus = CommentStatus.NEW
    draft_reply: Optional[str] = None    # AI 초안 (검토 후 발행)
    replied_at: Optional[datetime] = None
    reply_external_id: Optional[str] = None
    error: Optional[str] = None
    commented_at: Optional[datetime] = None
    fetched_at: datetime = Field(default_factory=now_utc)


class BreakoutPattern(BaseModel):
    """브레이크아웃 게시물의 AI 역설계 결과 — 재현 가능한 '승리 공식'.

    source='internal'은 본 계정 게시물(post_id 있음), 'external'은 외부/경쟁사
    바이럴 예시(post_id 없음, source_ref에 출처).
    """
    id: Optional[int] = None
    post_id: Optional[int] = None
    source: str = "internal"          # internal | external
    source_ref: Optional[str] = None  # 외부일 때 출처(URL/핸들/메모)
    breakout_score: float = 0.0
    hook_type: str = ""
    psychology_levers: list[str] = Field(default_factory=list)
    format: str = ""
    topic_angle: str = ""
    structure_notes: str = ""
    emotional_trigger: str = ""
    spread_hypothesis: str = ""       # 왜 공유/저장/팔로우로 이어졌나
    replicable_formula: str = ""      # 다음 콘텐츠에 주입할 재현 템플릿
    confidence: int = 0               # 0-100
    metrics_snapshot: dict = Field(default_factory=dict)
    detected_at: datetime = Field(default_factory=now_utc)


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
