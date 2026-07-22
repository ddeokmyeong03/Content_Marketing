from pathlib import Path
from functools import lru_cache
import anthropic
from jinja2 import Template

from ..config.brand_config import BrandConfig


SYSTEM_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "system_base.txt"


def build_brand_system_prompt(brand_config: BrandConfig) -> str:
    template_text = SYSTEM_PROMPT_TEMPLATE.read_text(encoding="utf-8")
    template = Template(template_text)
    return template.render(brand_context=brand_config.to_system_prompt_context())


def get_client(api_key: str) -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=api_key)


def make_cached_system_block(brand_config: BrandConfig) -> dict:
    """브랜드 시스템 프롬프트를 캐시 가능한 블록으로 반환"""
    return {
        "type": "text",
        "text": build_brand_system_prompt(brand_config),
        "cache_control": {"type": "ephemeral"},
    }
