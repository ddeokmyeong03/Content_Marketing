"""댓글 답글 생성 — 브랜드 톤으로 대화를 이어가는 짧은 답글 초안.

파싱은 순수 함수(`draft_from_tool_input`)로 분리해 API 없이 테스트 가능.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from jinja2 import Template

from ..config.brand_config import BrandConfig
from ..models.enums import Platform
from .client import get_client, make_cached_system_block

REPLY_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "reply_ko.txt"

REPLY_TOOL = {
    "name": "write_comment_reply",
    "description": "댓글에 대한 브랜드 톤 답글을 작성하거나, 응대 불필요로 분류합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "needs_reply": {"type": "boolean"},
            "reply": {"type": "string"},
            "intent": {
                "type": "string",
                "enum": ["question", "agreement", "experience", "objection", "spam", "other"],
            },
        },
        "required": ["needs_reply", "reply", "intent"],
    },
}


@dataclass
class ReplyDraft:
    needs_reply: bool
    reply: str
    intent: str


def draft_from_tool_input(data: dict) -> ReplyDraft:
    needs = bool(data.get("needs_reply", False))
    reply = (data.get("reply") or "").strip()
    return ReplyDraft(
        needs_reply=needs and bool(reply),
        reply=reply if needs else "",
        intent=data.get("intent", "other"),
    )


def generate_reply(
    brand_config: BrandConfig,
    api_key: str,
    comment_text: str,
    author: str,
    platform: Platform,
    post_topic: Optional[str] = None,
    post_caption: Optional[str] = None,
    model: str = "claude-opus-4-8",
) -> ReplyDraft:
    client = get_client(api_key)
    template = Template(REPLY_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    prompt = template.render(
        platform=platform.value,
        author=author or "user",
        comment_text=comment_text,
        post_topic=post_topic,
        post_caption=(post_caption or "")[:300],
    )
    response = client.messages.create(
        model=model,
        max_tokens=512,
        system=[make_cached_system_block(brand_config)],
        tools=[REPLY_TOOL],
        tool_choice={"type": "tool", "name": "write_comment_reply"},
        messages=[{"role": "user", "content": prompt}],
    )
    block = next((b for b in response.content if b.type == "tool_use"), None)
    if block is None:
        raise RuntimeError("Claude가 답글을 반환하지 않았습니다.")
    return draft_from_tool_input(block.input)
