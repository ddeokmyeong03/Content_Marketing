"""텍스트 카드 렌더링(1b) 검증.

HTML 생성은 순수 함수라 브라우저 없이 전부 검증한다. PNG 굽기는 브라우저가
필요하므로 사용할 수 없는 환경에서는 건너뛴다.
"""
import pytest

from branding.config import load_brand_config
from branding.config.brand_config import CarouselConfig
from branding.config.settings import Settings
from branding.db import PostRepository, init_db
from branding.models import CarouselSlide, Post, PostContent
from branding.models.enums import ContentPillar, MediaType, Platform
from branding.render import (
    CardPalette, RenderUnavailable, SlideRenderer, apply_emphasis, build_card_html, fit_font_px,
)
from branding.render.png import render_html_to_png


@pytest.fixture
def brand():
    return load_brand_config("brand/config.yaml")


# --- 폰트 자동 축소 ---

def test_font_stays_at_base_size_within_limit():
    assert fit_font_px("짧은 제목", target_chars=28, base_px=96, min_px=46) == 96


def test_font_shrinks_when_text_exceeds_limit():
    short = fit_font_px("가" * 28, target_chars=28, base_px=96, min_px=46)
    long = fit_font_px("가" * 56, target_chars=28, base_px=96, min_px=46)
    assert long < short
    assert long == 48   # 96 * 28/56


def test_font_never_goes_below_minimum():
    assert fit_font_px("가" * 500, target_chars=28, base_px=96, min_px=46) == 46


def test_empty_text_keeps_base_size():
    assert fit_font_px("", target_chars=28, base_px=96, min_px=46) == 96


# --- 강조 처리 ---

def test_emphasis_wraps_matching_terms():
    assert apply_emphasis("주 12시간을 되찾았다", ["12시간"]) == "주 <mark>12시간</mark>을 되찾았다"


def test_longer_terms_win_so_short_words_do_not_split_them():
    out = apply_emphasis("주 12시간 절약", ["12시간", "주 12시간"])
    assert "<mark>주 12시간</mark>" in out
    assert out.count("<mark>") == 1   # 중첩·분할 없이 한 번만


def test_html_in_text_is_escaped_before_emphasis():
    out = apply_emphasis('<script>alert("x")</script> 위험', ["위험"])
    assert "<script>" not in out
    assert "&lt;script&gt;" in out
    assert "<mark>위험</mark>" in out


def test_emphasis_term_containing_html_is_escaped_too():
    out = apply_emphasis("a & b 조합", ["a & b"])
    assert "<mark>a &amp; b</mark>" in out


def test_text_without_emphasis_is_still_escaped():
    assert apply_emphasis("<b>굵게</b>", []) == "&lt;b&gt;굵게&lt;/b&gt;"


def test_inserted_markup_is_not_rematched():
    # 'mark'가 강조어여도 삽입한 <mark> 태그를 다시 감싸면 안 된다
    out = apply_emphasis("mark 라는 단어", ["mark"])
    assert out.count("<mark>") == 1


# --- 팔레트 ---

def test_palette_reads_brand_colors(brand):
    palette = CardPalette.from_brand(brand)
    assert palette.background == brand.visual_aesthetic.color_palette[0]
    assert palette.text == brand.visual_aesthetic.color_palette[1]


def test_palette_falls_back_when_brand_defines_too_few_colors(brand):
    brand.visual_aesthetic.color_palette = ["#111111"]
    palette = CardPalette.from_brand(brand)
    assert palette.background == "#111111"
    assert palette.text and palette.accent and palette.muted   # 나머지는 기본값으로 채움


# --- 카드 HTML ---

def _slide(**kw) -> CarouselSlide:
    base = dict(index=1, role="hook", headline="자동화 실수", body="6개월을 날렸습니다",
                emphasis=["6개월"])
    base.update(kw)
    return CarouselSlide(**base)


def test_card_contains_text_counter_and_brand_styling(brand):
    html = build_card_html(_slide(), brand, total=7)

    assert "자동화 실수" in html
    assert "<mark>6개월</mark>" in html
    assert "1 / 7" in html                                  # 슬라이드 번호
    assert brand.carousel.font_family_css in html            # 브랜드 폰트 스택
    assert brand.visual_aesthetic.color_palette[0] in html   # 배경색
    assert f"width: {brand.carousel.width}px" in html


def test_card_uses_role_specific_layout_class(brand):
    assert 'class="card role-cta"' in build_card_html(_slide(role="cta"), brand, total=3)
    assert 'class="card role-hook"' in build_card_html(_slide(role="hook"), brand, total=3)


def test_card_omits_body_block_when_empty(brand):
    html = build_card_html(_slide(body="", emphasis=[]), brand, total=2)
    assert 'class="body"' not in html


def test_long_headline_gets_smaller_font(brand):
    short = build_card_html(_slide(headline="짧다", emphasis=[]), brand, total=2)
    long = build_card_html(_slide(headline="가" * 80, emphasis=[]), brand, total=2)

    def headline_px(html: str) -> int:
        marker = ".headline {\n    font-size: "
        return int(html.split(marker)[1].split("px")[0])

    assert headline_px(long) < headline_px(short)


def test_card_escapes_untrusted_text(brand):
    html = build_card_html(
        _slide(headline='<img src=x onerror="alert(1)">', body="", emphasis=[]),
        brand, total=1,
    )
    assert "<img" not in html
    assert "&lt;img" in html


def test_carousel_override_changes_canvas(brand):
    cfg = CarouselConfig(width=1080, height=1080)
    html = build_card_html(_slide(), brand, total=1, carousel=cfg)
    assert "height: 1080px" in html


# --- 서비스 ---

def test_render_post_without_slides_is_rejected(tmp_path, brand):
    settings = Settings(data_dir=tmp_path)
    init_db(settings.db_path)
    post = Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="t",
        content=PostContent(caption_ko="c", cta=""),
    )
    with pytest.raises(ValueError, match="슬라이드가 없습니다"):
        SlideRenderer(settings, brand).render_post(post)


def test_output_dir_is_scoped_per_post(tmp_path, brand):
    settings = Settings(data_dir=tmp_path)
    renderer = SlideRenderer(settings, brand)
    assert renderer.output_dir(7).name == "post_7"
    assert renderer.output_dir(7) != renderer.output_dir(8)


# --- 실제 PNG 굽기 (브라우저 필요) ---

def test_renders_png_at_exact_canvas_size(tmp_path, brand):
    html = build_card_html(_slide(), brand, total=3)
    out = tmp_path / "card.png"
    try:
        render_html_to_png(
            html, out, width=brand.carousel.width, height=brand.carousel.height
        )
    except RenderUnavailable as e:
        pytest.skip(f"브라우저 사용 불가: {e}")

    assert out.exists() and out.stat().st_size > 0
    assert out.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"   # PNG 시그니처


def test_render_post_fills_image_path_and_flags_oversized(tmp_path, brand):
    settings = Settings(data_dir=tmp_path)
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    limit = brand.carousel.headline_max_chars
    post = repo.save(Post(
        platform=Platform.INSTAGRAM, media_type=MediaType.CAROUSEL,
        content_pillar=ContentPillar.AUTOMATION_TIPS, topic="t",
        content=PostContent(caption_ko="c", cta="", slides=[
            CarouselSlide(index=1, role="hook", headline="짧은 훅"),
            CarouselSlide(index=2, role="cta", headline="가" * (limit + 10)),
        ]),
    ))

    try:
        rendered = SlideRenderer(settings, brand).render_post(post)
    except RenderUnavailable as e:
        pytest.skip(f"브라우저 사용 불가: {e}")

    assert [r.index for r in rendered] == [1, 2]
    assert all(r.path.exists() for r in rendered)
    assert rendered[0].oversized is False
    assert rendered[1].oversized is True          # 한도 초과를 검토자에게 알림

    # 렌더 경로가 저장되고, 공개 URL은 아직 비어 있어야 한다(업로드는 다음 단계)
    reloaded = repo.get_by_id(post.id)
    assert all(s.image_path for s in reloaded.content.slides)
    assert reloaded.content.missing_slide_images() == [1, 2]
