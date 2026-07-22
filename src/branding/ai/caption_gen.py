from datetime import datetime
from pathlib import Path
from typing import Optional
from jinja2 import Template
import anthropic

from ..config.brand_config import BrandConfig
from ..models import PostContent, ImageBrief, ContentPillar, Platform, MediaType
from .client import get_client, make_cached_system_block

CAPTION_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "caption_ko.txt"

# Claude가 반환할 JSON 스키마를 tools 방식으로 정의
POST_CONTENT_TOOL = {
    "name": "create_post_content",
    "description": "SNS 포스트 콘텐츠를 구조화된 형식으로 생성합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "caption_ko": {
                "type": "string",
                "description": "한국어 캡션 본문 (해시태그 제외)",
            },
            "caption_en": {
                "type": "string",
                "description": "영어 번역 캡션",
            },
            "hooks": {
                "type": "array",
                "items": {"type": "string"},
                "description": "다양한 스타일의 첫 문장 훅 3가지",
                "minItems": 3,
                "maxItems": 3,
            },
            "cta": {
                "type": "string",
                "description": "자연스러운 행동 유도 문구",
            },
            "hashtags_ko": {
                "type": "array",
                "items": {"type": "string"},
                "description": "한국어 해시태그 목록 (# 없이)",
            },
            "hashtags_en": {
                "type": "array",
                "items": {"type": "string"},
                "description": "영어 해시태그 목록 (# 없이)",
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
        "required": ["caption_ko", "hooks", "cta", "hashtags_ko", "hashtags_en"],
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
) -> PostContent:
    client = get_client(api_key)
    pillar_config = brand_config.get_pillar(pillar.value)
    pillar_name = pillar_config.name_ko if pillar_config else pillar.value

    template = Template(CAPTION_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    user_prompt = template.render(
        platform=platform.value,
        pillar_id=pillar.value,
        pillar_name=pillar_name,
        topic=topic,
        media_type=media_type.value,
        week_theme=week_theme,
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=[make_cached_system_block(brand_config)],
        tools=[POST_CONTENT_TOOL],
        tool_choice={"type": "tool", "name": "create_post_content"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_use_block = next(
        (b for b in response.content if b.type == "tool_use"),
        None,
    )
    if tool_use_block is None:
        raise RuntimeError("Claude가 구조화된 콘텐츠를 반환하지 않았습니다.")

    data = tool_use_block.input
    image_brief = None
    if data.get("image_brief") and media_type in (MediaType.IMAGE, MediaType.CAROUSEL):
        image_brief = ImageBrief(**data["image_brief"])

    return PostContent(
        caption_ko=data["caption_ko"],
        caption_en=data.get("caption_en"),
        hooks=data.get("hooks", []),
        cta=data.get("cta", ""),
        hashtags_ko=data.get("hashtags_ko", []),
        hashtags_en=data.get("hashtags_en", []),
        image_brief=image_brief,
    )
