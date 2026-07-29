from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field


class PersonaConfig(BaseModel):
    name: str = ""
    profession: str
    tagline_ko: str
    tagline_en: str
    bio_ko: str
    bio_en: str


class ToneConfig(BaseModel):
    primary: str
    secondary: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    korean_register: str = "해요체"
    emoji_usage: str = "minimal"


class ContentPillarConfig(BaseModel):
    id: str
    name_ko: str
    name_en: str
    description_ko: str
    weight: float
    examples: list[str] = Field(default_factory=list)


class VisualConfig(BaseModel):
    style: str
    color_palette: list[str] = Field(default_factory=list)
    font_preference: str
    image_style: str


class PlatformSchedule(BaseModel):
    frequency: int
    preferred_times: list[str]
    timezone: str


class InstagramSchedule(PlatformSchedule):
    media_mix: dict[str, float] = Field(default_factory=dict)


class ThreadsSchedule(PlatformSchedule):
    style: str = ""


class PostingScheduleConfig(BaseModel):
    instagram: InstagramSchedule
    threads: ThreadsSchedule


class LanguageConfig(BaseModel):
    primary: str = "ko"
    secondary: str = "en"
    bilingual: bool = True


class HashtagPlatformConfig(BaseModel):
    total: int
    brand_tags: list[str] = Field(default_factory=list)
    mix: dict[str, int] = Field(default_factory=dict)
    style: Optional[str] = None


class HashtagConfig(BaseModel):
    instagram: HashtagPlatformConfig
    threads: HashtagPlatformConfig


class AutomationConfig(BaseModel):
    auto_approve: bool = False
    review_reminder_hour: int = 8
    min_review_hours: int = 2


class AudienceConfig(BaseModel):
    """타깃 청중 정의 — 프롬프트에 고통/욕망/반론을 주입해 반응을 유도한다."""
    description_ko: str = ""
    pains: list[str] = Field(default_factory=list)       # 고통·불만
    desires: list[str] = Field(default_factory=list)     # 욕망·열망
    objections: list[str] = Field(default_factory=list)  # 반론·의심
    sophistication: str = "중급"                          # 초급 | 중급 | 고급 (메시지 각도 조절)


class PsychologyConfig(BaseModel):
    """행동심리 레버 및 설득 강도 설정."""
    intensity: str = "assertive_factual"  # honest | assertive_factual | aggressive
    levers: list[str] = Field(
        default_factory=lambda: [
            "curiosity_gap", "specificity", "pattern_interrupt",
            "loss_aversion", "social_proof",
        ]
    )
    banned_tactics: list[str] = Field(
        default_factory=lambda: ["허위 희소성", "거짓 수치", "낚시성 과장"]
    )


class EngagementConfig(BaseModel):
    """참여율 최적화 목표."""
    primary_metric: str = "saves"  # saves | comments | shares | follows
    secondary_metrics: list[str] = Field(default_factory=lambda: ["comments"])
    hook_variants: int = 5          # 생성·평가할 훅 개수
    min_hook_score: int = 70        # 이 점수 미만이면 캡션 1회 재생성


class DiscoveryConfig(BaseModel):
    """타깃 발굴 설정.

    ⚠️ 발굴까지만 자동화한다. 실제 팔로우·좋아요는 운영자가 직접 실행한다
    (공식 API에 엔드포인트가 없고 비공식 자동화는 ToS 위반).
    """
    hashtags: list[str] = Field(default_factory=list)       # 비우면 브랜드 태그 사용
    seed_accounts: list[str] = Field(default_factory=list)  # business_discovery로 조회할 계정
    daily_checklist: int = 15        # 하루 실행 목록 크기
    min_followers: int = 500         # 목표 팔로워 구간
    max_followers: int = 50000
    max_hashtag_queries_per_week: int = 30  # Instagram 제한 (7일 고유 30개)


class CarouselConfig(BaseModel):
    """캐러셀 슬라이드 생성·렌더링 기준.

    글자수 한도는 프롬프트에 주입되어 '카드에 실제로 들어가는 분량'을 통제한다.
    렌더러는 한도를 넘겨도 폰트 크기를 줄여 담아내지만, 넘길수록 가독성이 떨어진다.
    """
    slides: int = 7                 # 생성할 슬라이드 수 (Instagram 허용: 2~10)
    headline_max_chars: int = 28    # 카드 큰 글씨 최대 길이
    body_max_chars: int = 80        # 보조 문구 최대 길이
    # 렌더링 캔버스 — Instagram 세로형 권장 비율 4:5
    width: int = 1080
    height: int = 1350
    font_family_css: str = (
        '"Pretendard", "Noto Sans KR", "Apple SD Gothic Neo", "Malgun Gothic", '
        '"NanumGothic", "WenQuanYi Zen Hei", sans-serif'
    )


class AnalysisConfig(BaseModel):
    """브레이크아웃 판정 기준 (표본이 적은 초기 계정 대응 포함)."""
    z_threshold: float = 2.5      # 이 가중 z 이상이면 브레이크아웃
    min_samples: int = 8          # 이 미만이면 z-score 대신 잠정 판정 모드
    provisional_ratio: float = 2.0  # 잠정 모드: 중앙값 대비 이 배수 이상이면 잠정 브레이크아웃


class BrandConfig(BaseModel):
    persona: PersonaConfig
    tone_of_voice: ToneConfig
    content_pillars: list[ContentPillarConfig]
    visual_aesthetic: VisualConfig
    posting_schedule: PostingScheduleConfig
    language: LanguageConfig
    hashtag_strategy: HashtagConfig
    automation: AutomationConfig
    # 참여 엔진 (없으면 기본값 — 기존 config.yaml과 하위 호환)
    niche: str = ""
    audience: AudienceConfig = Field(default_factory=AudienceConfig)
    psychology: PsychologyConfig = Field(default_factory=PsychologyConfig)
    engagement: EngagementConfig = Field(default_factory=EngagementConfig)
    analysis: AnalysisConfig = Field(default_factory=AnalysisConfig)
    carousel: CarouselConfig = Field(default_factory=CarouselConfig)
    discovery: DiscoveryConfig = Field(default_factory=DiscoveryConfig)

    def get_pillar(self, pillar_id: str) -> Optional[ContentPillarConfig]:
        return next((p for p in self.content_pillars if p.id == pillar_id), None)

    def to_system_prompt_context(self) -> str:
        """AI 시스템 프롬프트에 삽입할 브랜드 컨텍스트 문자열 생성"""
        pillars_text = "\n".join(
            f"  - [{p.id}] {p.name_ko} (비중 {int(p.weight * 100)}%): {p.description_ko}"
            for p in self.content_pillars
        )
        avoid_text = ", ".join(self.tone_of_voice.avoid)
        niche_text = f"\n세부 니치: {self.niche}" if self.niche else ""
        audience_block = ""
        a = self.audience
        if a.description_ko or a.pains or a.desires:
            parts = [f"\n## 타깃 청중{(' — ' + a.description_ko) if a.description_ko else ''}"]
            if a.pains:
                parts.append("고통·불만: " + ", ".join(a.pains))
            if a.desires:
                parts.append("욕망·열망: " + ", ".join(a.desires))
            if a.objections:
                parts.append("반론·의심: " + ", ".join(a.objections))
            parts.append(f"인지 수준: {a.sophistication}")
            audience_block = "\n".join(parts)
        return f"""## 브랜드 정체성
직업: {self.persona.profession}{niche_text}
태그라인: {self.persona.tagline_ko}

바이오:
{self.persona.bio_ko.strip()}
{audience_block}

## 톤 오브 보이스
- 핵심 톤: {self.tone_of_voice.primary}
- 부가 특성: {", ".join(self.tone_of_voice.secondary)}
- 반드시 피할 것: {avoid_text}
- 경어: {self.tone_of_voice.korean_register} 사용
- 이모지: {self.tone_of_voice.emoji_usage} (최소화)

## 콘텐츠 기둥
{pillars_text}

## 시각적 스타일
{self.visual_aesthetic.style}

## 언어 규칙
- 한국어 우선 작성, 영어 번역 병기
- 맞춤법과 띄어쓰기 철저히 준수
- 자연스러운 {self.tone_of_voice.korean_register} 사용
- 과도한 감탄사 금지"""


def load_brand_config(config_path: str | Path = "brand/config.yaml") -> BrandConfig:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"브랜드 설정 파일을 찾을 수 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return BrandConfig(**data)
