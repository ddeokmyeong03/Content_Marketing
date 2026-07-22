from datetime import date, timedelta
from pathlib import Path
from typing import Optional
from jinja2 import Template
import anthropic

from ..config.brand_config import BrandConfig
from ..models import ContentPlan, ContentPlanTopic, Platform, MediaType, ContentPillar
from .client import get_client, make_cached_system_block

PLAN_PROMPT_TEMPLATE = Path(__file__).parent / "prompts" / "content_plan.txt"

PLAN_TOOL = {
    "name": "create_content_plan",
    "description": "주간 SNS 콘텐츠 캘린더를 생성합니다",
    "input_schema": {
        "type": "object",
        "properties": {
            "theme": {"type": "string", "description": "이번 주 영어 테마"},
            "theme_ko": {"type": "string", "description": "이번 주 한국어 테마"},
            "topics": {
                "type": "array",
                "description": "각 포스트 계획 목록",
                "items": {
                    "type": "object",
                    "properties": {
                        "pillar": {
                            "type": "string",
                            "enum": ["startup_reality", "automation_tips", "business_growth", "mindset"],
                        },
                        "topic": {"type": "string", "description": "포스트 주제 (한국어)"},
                        "platform": {"type": "string", "enum": ["instagram", "threads"]},
                        "day_offset": {"type": "integer", "minimum": 0, "maximum": 6, "description": "0=월요일"},
                        "media_type": {
                            "type": "string",
                            "enum": ["text", "image", "carousel"],
                            "default": "image",
                        },
                    },
                    "required": ["pillar", "topic", "platform", "day_offset"],
                },
            },
        },
        "required": ["theme", "theme_ko", "topics"],
    },
}


def generate_weekly_plan(
    brand_config: BrandConfig,
    api_key: str,
    week_start: Optional[date] = None,
    recent_topics: Optional[list[str]] = None,
) -> ContentPlan:
    if week_start is None:
        today = date.today()
        # 이번 주 월요일
        week_start = today - timedelta(days=today.weekday())
    week_end = week_start + timedelta(days=6)

    total_posts = (
        brand_config.posting_schedule.instagram.frequency
        + brand_config.posting_schedule.threads.frequency
    )

    template = Template(PLAN_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    user_prompt = template.render(
        week_start=week_start.strftime("%Y-%m-%d"),
        week_end=week_end.strftime("%Y-%m-%d"),
        instagram_freq=brand_config.posting_schedule.instagram.frequency,
        threads_freq=brand_config.posting_schedule.threads.frequency,
        pillars=brand_config.content_pillars,
        recent_topics=recent_topics or [],
        total_posts=total_posts,
    )

    client = get_client(api_key)
    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=2048,
        system=[make_cached_system_block(brand_config)],
        tools=[PLAN_TOOL],
        tool_choice={"type": "tool", "name": "create_content_plan"},
        messages=[{"role": "user", "content": user_prompt}],
    )

    tool_block = next((b for b in response.content if b.type == "tool_use"), None)
    if tool_block is None:
        raise RuntimeError("Claude가 콘텐츠 계획을 반환하지 않았습니다.")

    data = tool_block.input
    topics = [
        ContentPlanTopic(
            pillar=ContentPillar(t["pillar"]),
            topic=t["topic"],
            platform=Platform(t["platform"]),
            day_offset=t["day_offset"],
            media_type=MediaType(t.get("media_type", "image")),
        )
        for t in data["topics"]
    ]

    return ContentPlan(
        week_start=week_start,
        week_end=week_end,
        theme=data["theme"],
        theme_ko=data["theme_ko"],
        topics=topics,
    )
