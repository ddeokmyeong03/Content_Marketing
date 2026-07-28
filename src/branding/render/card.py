"""슬라이드 → HTML/CSS 카드 (순수 함수).

AI 이미지 모델은 한글 텍스트를 자주 깨뜨린다. 텍스트 카드는 브라우저로 렌더링하면
한글이 완벽하고 브랜드 색·폰트가 매번 동일하게 나오므로, 문구가 들어가는 카드는
여기서 HTML로 만들고 헤드리스 크로미엄으로 PNG를 굽는다(`render/png.py`).

이 모듈은 브라우저에 의존하지 않아 오프라인에서 그대로 테스트할 수 있다.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass

from ..config.brand_config import BrandConfig, CarouselConfig
from ..models import CarouselSlide

# 역할별 강조 — 첫 장은 시선을 잡고, 마지막 장은 행동을 부른다
ROLE_LABELS: dict[str, str] = {
    "hook": "",
    "body": "",
    "proof": "근거",
    "cta": "",
}

# 팔레트 기본값 (brand config의 visual_aesthetic.color_palette가 없을 때)
_FALLBACK_PALETTE = ["#0A0A0A", "#FFFFFF", "#F5F0E8", "#1A1A1A"]

_HEADLINE_BASE_PX = 96
_HEADLINE_MIN_PX = 46
_BODY_BASE_PX = 40
_BODY_MIN_PX = 26


@dataclass
class CardPalette:
    background: str
    text: str
    accent: str
    muted: str

    @classmethod
    def from_brand(cls, brand: BrandConfig) -> "CardPalette":
        colors = list(getattr(brand.visual_aesthetic, "color_palette", None) or [])
        colors += _FALLBACK_PALETTE[len(colors):]
        return cls(background=colors[0], text=colors[1], accent=colors[2], muted=colors[3])


def fit_font_px(text: str, target_chars: int, base_px: int, min_px: int) -> int:
    """글자 수에 맞춰 폰트 크기를 줄인다.

    한도(`target_chars`) 안이면 기본 크기를 그대로 쓰고, 넘으면 넘긴 비율만큼
    줄여 카드 밖으로 넘치지 않게 한다. 문구를 잘라내지 않는 대신 크기로 흡수한다.
    """
    length = len(text.strip())
    if length <= target_chars or length == 0:
        return base_px
    scaled = int(base_px * target_chars / length)
    return max(min_px, scaled)


def apply_emphasis(text: str, emphasis: list[str]) -> str:
    """HTML 이스케이프 후 강조 문자열을 <mark>로 감싼다.

    이스케이프를 먼저 하므로 본문에 든 <,& 가 마크업을 깨지 않고,
    치환은 한 번의 정규식 통과로 처리해 삽입한 태그가 다시 매칭되지 않는다.
    """
    escaped = html.escape(text)
    terms = [html.escape(t.strip()) for t in emphasis if t and t.strip()]
    if not terms:
        return escaped
    # 긴 것부터 매칭해야 짧은 단어가 긴 구절을 쪼개지 않는다
    pattern = "|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True))
    return re.sub(pattern, lambda m: f"<mark>{m.group(0)}</mark>", escaped)


def build_card_html(
    slide: CarouselSlide,
    brand: BrandConfig,
    total: int,
    carousel: CarouselConfig | None = None,
) -> str:
    """슬라이드 한 장을 완결된 HTML 문서로 만든다."""
    cfg = carousel or brand.carousel
    palette = CardPalette.from_brand(brand)

    headline_px = fit_font_px(
        slide.headline, cfg.headline_max_chars, _HEADLINE_BASE_PX, _HEADLINE_MIN_PX
    )
    body_px = fit_font_px(slide.body, cfg.body_max_chars, _BODY_BASE_PX, _BODY_MIN_PX)

    headline_html = apply_emphasis(slide.headline, slide.emphasis)
    body_html = apply_emphasis(slide.body, slide.emphasis) if slide.body else ""
    label = ROLE_LABELS.get(slide.role, "")

    role_class = f"role-{html.escape(slide.role or 'body')}"
    counter = f"{slide.index} / {total}"

    parts = [
        f'<div class="label">{html.escape(label)}</div>' if label else "",
        f'<h1 class="headline">{headline_html}</h1>',
        f'<p class="body">{body_html}</p>' if body_html else "",
    ]
    content = "\n      ".join(p for p in parts if p)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: {cfg.width}px; height: {cfg.height}px;
    background: {palette.background};
    font-family: {cfg.font_family_css};
    -webkit-font-smoothing: antialiased;
  }}
  .card {{
    width: 100%; height: 100%;
    padding: 96px 88px;
    display: flex; flex-direction: column; justify-content: center;
    position: relative;
    color: {palette.text};
  }}
  .card.role-hook {{ justify-content: center; }}
  .card.role-cta {{ justify-content: flex-end; padding-bottom: 200px; }}
  .label {{
    font-size: 30px; font-weight: 600; letter-spacing: .18em;
    color: {palette.accent}; opacity: .75; margin-bottom: 28px;
  }}
  .headline {{
    font-size: {headline_px}px; font-weight: 800; line-height: 1.28;
    letter-spacing: -.02em; word-break: keep-all; white-space: pre-wrap;
  }}
  .body {{
    margin-top: 40px;
    font-size: {body_px}px; font-weight: 400; line-height: 1.6;
    color: {palette.text}; opacity: .78;
    word-break: keep-all; white-space: pre-wrap;
  }}
  /* 강조는 색만으로는 약하다 — 팔레트가 저대비여도 보이도록 밑줄을 함께 준다 */
  mark {{
    background: none; color: {palette.accent}; font-weight: 800;
    box-shadow: inset 0 -.14em 0 {palette.accent};
    padding-bottom: .04em;
  }}
  .counter {{
    position: absolute; right: 88px; bottom: 72px;
    font-size: 28px; font-weight: 600; color: {palette.text}; opacity: .45;
  }}
  .rule {{
    position: absolute; left: 88px; bottom: 82px;
    width: 96px; height: 6px; background: {palette.accent}; opacity: .9;
  }}
</style>
</head>
<body>
  <div class="card {role_class}">
      {content}
    <div class="rule"></div>
    <div class="counter">{html.escape(counter)}</div>
  </div>
</body>
</html>
"""
