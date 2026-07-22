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


class BrandConfig(BaseModel):
    persona: PersonaConfig
    tone_of_voice: ToneConfig
    content_pillars: list[ContentPillarConfig]
    visual_aesthetic: VisualConfig
    posting_schedule: PostingScheduleConfig
    language: LanguageConfig
    hashtag_strategy: HashtagConfig
    automation: AutomationConfig

    def get_pillar(self, pillar_id: str) -> Optional[ContentPillarConfig]:
        return next((p for p in self.content_pillars if p.id == pillar_id), None)

    def to_system_prompt_context(self) -> str:
        """AI 시스템 프롬프트에 삽입할 브랜드 컨텍스트 문자열 생성"""
        pillars_text = "\n".join(
            f"  - [{p.id}] {p.name_ko} (비중 {int(p.weight * 100)}%): {p.description_ko}"
            for p in self.content_pillars
        )
        avoid_text = ", ".join(self.tone_of_voice.avoid)
        return f"""## 브랜드 정체성
직업: {self.persona.profession}
태그라인: {self.persona.tagline_ko}

바이오:
{self.persona.bio_ko.strip()}

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
