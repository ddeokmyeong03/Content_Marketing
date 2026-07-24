from pathlib import Path
from typing import Optional
from jinja2 import Template

from ..config.brand_config import BrandConfig
from ..models import (
    PostContent, ImageBrief, HookVariant, BreakoutPattern,
    ContentPillar, Platform, MediaType,
)
from . import psychology
from .client import get_client, make_cached_system_block

CAPTION_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "caption_ko.txt"


def _build_tool(hook_variants: int) -> dict:
    """참여 엔진 산출물을 담는 tool 스키마. 훅 개수를 config에 맞춰 주입."""
    return {
        "name": "create_post_content",
        "description": "참여율 최적화된 SNS 포스트 콘텐츠를 구조화된 형식으로 생성합니다",
        "input_schema": {
            "type": "object",
            "properties": {
                "hook_variants": {
                    "type": "array",
                    "description": f"서로 다른 심리 기법을 쓴 훅 후보 {hook_variants}개",
                    "minItems": max(1, hook_variants),
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string", "description": "훅 문장"},
                            "technique": {"type": "string", "description": "사용한 훅/레버 id"},
                            "predicted_score": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 100,
                                "description": "자기예측 참여 점수",
                            },
                        },
                        "required": ["text", "technique", "predicted_score"],
                    },
                },
                "chosen_hook": {
                    "type": "string",
                    "description": "채택한 훅 (캡션 첫 줄)",
                },
                "caption_ko": {"type": "string", "description": "한국어 캡션 본문 (해시태그 제외)"},
                "caption_en": {"type": "string", "description": "영어 번역 캡션"},
                "cta": {"type": "string", "description": "목표 지표를 겨냥한 행동 유도 문구"},
                "hashtags_ko": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "한국어 해시태그 (# 없이)",
                },
                "hashtags_en": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "영어 해시태그 (# 없이)",
                },
                "image_brief": {
                    "type": "object",
                    "description": "이미지/비주얼 브리프 (이미지 포스트인 경우)",
                    "properties": {
                        "description": {"type": "string"},
                        "style_notes": {"type": "string"},
                        "text_overlay": {"type": "string"},
                        "color_hints": {"type": "array", "items": {"type": "string"}},
                        "midjourney_prompt": {"type": "string"},
                        "dall_e_prompt": {"type": "string"},
                    },
                    "required": ["description", "style_notes", "midjourney_prompt", "dall_e_prompt"],
                },
            },
            "required": [
                "hook_variants", "chosen_hook", "caption_ko", "cta",
                "hashtags_ko", "hashtags_en",
            ],
        },
    }


def generate_caption(
    brand_config: BrandConfig,
    api_key: str,
    topic: str,
    pillar: ContentPillar,
    platform: Platform,
    media_type: MediaType,
    week_theme: Optional[str] = None,
    model: str = "claude-opus-4-8",
    extra_guidance: Optional[str] = None,
    winning_patterns: Optional[list[BreakoutPattern]] = None,
) -> PostContent:
    client = get_client(api_key)
    pillar_config = brand_config.get_pillar(pillar.value)
    pillar_name = pillar_config.name_ko if pillar_config else pillar.value

    eng = brand_config.engagement
    psy = brand_config.psychology

    template = Template(CAPTION_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    user_prompt = template.render(
        platform=platform.value,
        pillar_id=pillar.value,
        pillar_name=pillar_name,
        topic=topic,
        media_type=media_type.value,
        week_theme=week_theme,
        primary_metric=eng.primary_metric,
        cta_strategy=psychology.cta_strategy(eng.primary_metric),
        intensity_guide=psychology.intensity_guide(psy.intensity),
        levers_text=psychology.render_levers(psy.levers),
        hook_types_text=psychology.render_hook_types(),
        banned_tactics=", ".join(psy.banned_tactics),
        hook_variants=eng.hook_variants,
        winning_patterns=winning_patterns or [],
    )
    if extra_guidance:
        user_prompt += f"\n\n## 개선 지시 (이전 초안 평가 반영)\n{extra_guidance}"

    response = client.messages.create(
        model=model,
        max_tokens=2560,
        system=[make_cached_system_block(brand_config)],
        tools=[_build_tool(eng.hook_variants)],
        tool_choice={"type": "tool", "name": "create_post_content"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_use_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_use_block is None:
        raise RuntimeError("Claude가 구조화된 콘텐츠를 반환하지 않았습니다.")

    data = tool_use_block.input
    image_brief = None
    if data.get("image_brief") and media_type in (MediaType.IMAGE, MediaType.CAROUSEL):
        image_brief = ImageBrief(**data["image_brief"])

    variants = [HookVariant(**h) for h in data.get("hook_variants", [])]

    return PostContent(
        caption_ko=data["caption_ko"],
        caption_en=data.get("caption_en"),
        hooks=[v.text for v in variants],
        hook_variants=variants,
        chosen_hook=data.get("chosen_hook"),
        cta=data.get("cta", ""),
        hashtags_ko=data.get("hashtags_ko", []),
        hashtags_en=data.get("hashtags_en", []),
        image_brief=image_brief,
    )
