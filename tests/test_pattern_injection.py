"""P5: 승리 공식이 생성 프롬프트에 재주입되는지 (템플릿 렌더링 검증)."""
from jinja2 import Template

from branding.ai.caption_gen import CAPTION_PROMPT_TEMPLATE
from branding.ai.content_planner import PLAN_PROMPT_TEMPLATE
from branding.models import BreakoutPattern


def _pattern() -> BreakoutPattern:
    return BreakoutPattern(
        post_id=1, breakout_score=72, hook_type="contrarian_hook",
        topic_angle="실패 고백", psychology_levers=["contrarian", "specificity"],
        replicable_formula="[통념 반박]+[구체 수치]+[정체성 호명]",
        spread_hypothesis="공유율이 튄 것은 정체성 공감 때문",
    )


def _caption_ctx(**extra):
    ctx = dict(
        platform="instagram", pillar_id="startup_reality", pillar_name="창업 현실",
        topic="번아웃", media_type="carousel", week_theme=None,
        primary_metric="saves", cta_strategy="저장 유도", intensity_guide="사실 기반",
        levers_text="- 호기심 갭", hook_types_text="- 숫자 훅", banned_tactics="낚시",
        hook_variants=5, winning_patterns=[],
    )
    ctx.update(extra)
    return ctx


def test_caption_prompt_injects_winning_patterns():
    tpl = Template(CAPTION_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    out = tpl.render(**_caption_ctx(winning_patterns=[_pattern()]))
    assert "검증된 승리 공식" in out
    assert "[통념 반박]+[구체 수치]+[정체성 호명]" in out
    assert "contrarian, specificity" in out       # levers join


def test_caption_prompt_no_block_when_empty():
    tpl = Template(CAPTION_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    out = tpl.render(**_caption_ctx(winning_patterns=[]))
    assert "검증된 승리 공식" not in out


def test_plan_prompt_injects_winning_patterns():
    tpl = Template(PLAN_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    out = tpl.render(
        week_start="2026-07-27", week_end="2026-08-02", instagram_freq=4, threads_freq=7,
        pillars=[], recent_topics=[], top_performers=[], total_posts=11,
        winning_patterns=[_pattern()],
    )
    assert "검증된 승리 공식" in out
    assert "실패 고백" in out
    assert "[통념 반박]+[구체 수치]+[정체성 호명]" in out
