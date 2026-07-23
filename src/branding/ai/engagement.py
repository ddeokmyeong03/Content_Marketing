"""참여율 자기평가 · 최적화 루프.

캡션을 생성한 뒤 루브릭으로 자기평가(reflection)하고, 임계 점수 미만이면
평가 코멘트를 반영해 1회 재생성한다. '언어로 반응을 유도하는' 품질을 끌어올리는
핵심 단계.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Template

from ..config.brand_config import BrandConfig
from ..models import PostContent, ContentPillar, Platform, MediaType
from .caption_gen import generate_caption
from .client import get_client, make_cached_system_block

logger = logging.getLogger("branding.ai")

SCORE_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "engagement_score.txt"

SCORE_TOOL = {
    "name": "score_engagement",
    "description": "포스트 초안의 참여율을 루브릭으로 평가합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "overall": {"type": "integer", "minimum": 0, "maximum": 100},
            "scroll_stop": {"type": "integer", "minimum": 0, "maximum": 100},
            "specificity": {"type": "integer", "minimum": 0, "maximum": 100},
            "emotional_pull": {"type": "integer", "minimum": 0, "maximum": 100},
            "cta_fit": {"type": "integer", "minimum": 0, "maximum": 100},
            "verdict": {"type": "string", "enum": ["pass", "revise"]},
            "improvement_notes": {"type": "string"},
        },
        "required": ["overall", "verdict", "improvement_notes"],
    },
}


@dataclass
class EngagementEvaluation:
    overall: int
    verdict: str
    notes: str


def evaluate_caption(
    brand_config: BrandConfig,
    api_key: str,
    content: PostContent,
    platform: Platform,
    model: str = "claude-opus-4-8",
) -> EngagementEvaluation:
    client = get_client(api_key)
    template = Template(SCORE_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    prompt = template.render(
        platform=platform.value,
        primary_metric=brand_config.engagement.primary_metric,
        audience=brand_config.audience.description_ko or brand_config.niche or "정의된 청중",
        chosen_hook=content.chosen_hook or (content.hooks[0] if content.hooks else ""),
        caption=content.caption_ko,
        cta=content.cta,
    )
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=[make_cached_system_block(brand_config)],
        tools=[SCORE_TOOL],
        tool_choice={"type": "tool", "name": "score_engagement"},
        messages=[{"role": "user", "content": prompt}],
    )
    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("Claude가 평가 결과를 반환하지 않았습니다.")
    d = block.input
    return EngagementEvaluation(
        overall=int(d["overall"]),
        verdict=d.get("verdict", "pass"),
        notes=d.get("improvement_notes", ""),
    )


def generate_optimized_caption(
    brand_config: BrandConfig,
    api_key: str,
    topic: str,
    pillar: ContentPillar,
    platform: Platform,
    media_type: MediaType,
    week_theme: Optional[str] = None,
    model: str = "claude-opus-4-8",
) -> PostContent:
    """생성 → 자기평가 → (임계 미만이면) 1회 개선 재생성 → 최고 점수 반환."""
    threshold = brand_config.engagement.min_hook_score

    def _make(extra: Optional[str] = None) -> tuple[PostContent, EngagementEvaluation]:
        content = generate_caption(
            brand_config, api_key, topic, pillar, platform, media_type,
            week_theme=week_theme, model=model, extra_guidance=extra,
        )
        ev = evaluate_caption(brand_config, api_key, content, platform, model=model)
        content.engagement_score = ev.overall
        content.engagement_notes = ev.notes
        return content, ev

    content, ev = _make()
    logger.info("참여 점수 %d (임계 %d) — %s", ev.overall, threshold, topic[:30])

    if ev.overall >= threshold and ev.verdict == "pass":
        return content

    # 평가 코멘트를 반영해 1회 개선 재생성
    improved, ev2 = _make(extra=ev.notes)
    logger.info("개선 재생성 점수 %d (이전 %d)", ev2.overall, ev.overall)
    return improved if ev2.overall >= ev.overall else content
