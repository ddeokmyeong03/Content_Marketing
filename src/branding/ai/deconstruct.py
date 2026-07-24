"""브레이크아웃 게시물 AI 역설계 → 재현 가능한 '승리 공식'.

탐지된 브레이크아웃 게시물의 텍스트·지표를 Claude에게 넣어 왜 떴는지 구조 분해한다.
파싱 로직(`pattern_from_tool_input`)은 순수 함수로 분리해 API 없이 테스트 가능.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from jinja2 import Template

from ..config.brand_config import BrandConfig
from ..models import BreakoutPattern, Post
from ..models.enums import Platform
from .client import get_client, make_cached_system_block

DECONSTRUCT_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "deconstruct.txt"

DECONSTRUCT_TOOL = {
    "name": "score_breakout_pattern",
    "description": "브레이크아웃 게시물을 재현 가능한 승리 공식으로 역설계합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "hook_type": {"type": "string"},
            "psychology_levers": {"type": "array", "items": {"type": "string"}},
            "format": {"type": "string"},
            "topic_angle": {"type": "string"},
            "structure_notes": {"type": "string"},
            "emotional_trigger": {"type": "string"},
            "spread_hypothesis": {"type": "string"},
            "replicable_formula": {"type": "string"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        },
        "required": [
            "hook_type", "psychology_levers", "spread_hypothesis",
            "replicable_formula", "confidence",
        ],
    },
}


def pattern_from_tool_input(
    data: dict, post_id: int, breakout_score: float, metrics_snapshot: dict
) -> BreakoutPattern:
    """도구 응답(dict)을 BreakoutPattern으로 변환 (순수 함수, 테스트 대상)."""
    return BreakoutPattern(
        post_id=post_id,
        breakout_score=breakout_score,
        hook_type=data.get("hook_type", ""),
        psychology_levers=data.get("psychology_levers", []),
        format=data.get("format", ""),
        topic_angle=data.get("topic_angle", ""),
        structure_notes=data.get("structure_notes", ""),
        emotional_trigger=data.get("emotional_trigger", ""),
        spread_hypothesis=data.get("spread_hypothesis", ""),
        replicable_formula=data.get("replicable_formula", ""),
        confidence=int(data.get("confidence", 0)),
        metrics_snapshot=metrics_snapshot,
    )


def deconstruct_breakout(
    brand_config: BrandConfig,
    api_key: str,
    post: Post,
    breakout_score: float,
    reasons: list[str],
    metrics_snapshot: dict,
    platform: Platform,
    model: str = "claude-opus-4-8",
) -> BreakoutPattern:
    client = get_client(api_key)
    template = Template(DECONSTRUCT_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    prompt = template.render(
        platform=platform.value,
        topic=post.topic,
        breakout_score=breakout_score,
        reasons=", ".join(reasons) or "-",
        m=metrics_snapshot,
        chosen_hook=post.content.chosen_hook or (post.content.hooks[0] if post.content.hooks else ""),
        caption=post.content.caption_ko,
    )
    response = client.messages.create(
        model=model,
        max_tokens=1536,
        system=[make_cached_system_block(brand_config)],
        tools=[DECONSTRUCT_TOOL],
        tool_choice={"type": "tool", "name": "score_breakout_pattern"},
        messages=[{"role": "user", "content": prompt}],
    )
    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("Claude가 역설계 결과를 반환하지 않았습니다.")
    return pattern_from_tool_input(block.input, post.id, breakout_score, metrics_snapshot)
