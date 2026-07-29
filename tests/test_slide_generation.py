"""캐러셀 슬라이드 문구 생성(1a) 검증.

카드에 인쇄될 문구는 캡션과 요구사항이 다르다 — 분량이 곧 가독성이므로
글자수 한도를 config에서 프롬프트로 밀어넣고, 파싱 단계에서 순서·강조를 정돈한다.
"""
from jinja2 import Template

from branding.ai.caption_gen import (
    CAPTION_PROMPT_TEMPLATE, SLIDE_ROLES, _build_tool, _parse_slides, _slides_schema,
)
from branding.config.brand_config import CarouselConfig


# --- tool 스키마 ---

def test_slides_are_absent_for_non_carousel_posts():
    schema = _build_tool(hook_variants=5)["input_schema"]
    assert "slides" not in schema["properties"]
    assert "slides" not in schema["required"]


def test_slides_are_required_for_carousel_posts():
    schema = _build_tool(hook_variants=5, carousel=CarouselConfig())["input_schema"]
    assert "slides" in schema["properties"]
    assert "slides" in schema["required"]
    # 기존 필드는 그대로 유지되어야 한다
    assert "caption_ko" in schema["required"]
    assert "hook_variants" in schema["required"]


def test_slide_schema_carries_config_limits_into_the_prompt():
    cfg = CarouselConfig(slides=5, headline_max_chars=20, body_max_chars=60)
    schema = _slides_schema(cfg)

    assert "5장" in schema["description"]
    props = schema["items"]["properties"]
    assert "20자" in props["headline"]["description"]
    assert "60자" in props["body"]["description"]
    # Instagram 플랫폼 한도
    assert schema["minItems"] == 2
    assert schema["maxItems"] == 10
    assert props["role"]["enum"] == SLIDE_ROLES
    assert schema["items"]["required"] == ["role", "headline"]


# --- 응답 파싱 ---

def test_index_follows_array_order():
    slides = _parse_slides([
        {"role": "hook", "headline": "첫 장"},
        {"role": "body", "headline": "둘째 장"},
        {"role": "cta", "headline": "셋째 장"},
    ])
    assert [s.index for s in slides] == [1, 2, 3]
    assert [s.role for s in slides] == ["hook", "body", "cta"]


def test_emphasis_not_present_in_text_is_dropped():
    """렌더러는 문자열 매칭으로 강조하므로, 없는 문자열은 조용히 무시된다.

    파싱에서 걸러 두면 검토자가 '강조했는데 왜 안 보이지'로 헤매지 않는다.
    """
    slides = _parse_slides([{
        "role": "hook",
        "headline": "주 12시간을 되찾았습니다",
        "body": "반복 업무를 하나로 합쳤습니다",
        "emphasis": ["주 12시간", "하나로", "존재하지 않는 문구"],
    }])
    assert slides[0].emphasis == ["주 12시간", "하나로"]


def test_emphasis_matches_across_headline_and_body():
    slides = _parse_slides([{
        "headline": "도구가 아니라 흐름", "body": "흐름을 바꿔야 합니다",
        "emphasis": ["흐름"],
    }])
    assert slides[0].emphasis == ["흐름"]


def test_missing_role_defaults_by_position():
    slides = _parse_slides([{"headline": "첫 장"}, {"headline": "둘째 장"}])
    assert slides[0].role == "hook"    # 첫 장은 훅
    assert slides[1].role == "body"


def test_whitespace_is_trimmed_and_empty_body_allowed():
    slides = _parse_slides([{"role": "hook", "headline": "  제목  ", "body": "   "}])
    assert slides[0].headline == "제목"
    assert slides[0].body == ""


def test_blank_emphasis_entries_are_ignored():
    slides = _parse_slides([{"headline": "제목", "emphasis": ["", "  ", None]}])
    assert slides[0].emphasis == []


# --- 프롬프트 템플릿 ---

def _render_prompt(**kw) -> str:
    template = Template(CAPTION_PROMPT_TEMPLATE.read_text(encoding="utf-8"))
    base = dict(
        platform="instagram", pillar_id="automation_tips", pillar_name="자동화",
        topic="주제", media_type="carousel", week_theme=None, primary_metric="saves",
        cta_strategy="", intensity_guide="", levers_text="", hook_types_text="",
        banned_tactics="", hook_variants=5, winning_patterns=[], carousel=None,
    )
    base.update(kw)
    return template.render(**base)


def test_prompt_includes_slide_instructions_only_for_carousel():
    cfg = CarouselConfig(slides=6, headline_max_chars=24, body_max_chars=70)

    with_slides = _render_prompt(carousel=cfg)
    assert "캐러셀 슬라이드 (slides) — 6장" in with_slides
    assert "24자 이내" in with_slides
    assert "70자 이내" in with_slides

    without = _render_prompt(media_type="image", carousel=None)
    assert "캐러셀 슬라이드" not in without


def test_prompt_still_asks_for_image_brief_on_carousel():
    """슬라이드 구조가 추가돼도 기존 이미지 브리프 요구는 유지된다."""
    rendered = _render_prompt(carousel=CarouselConfig())
    assert "image_brief" in rendered
