from pathlib import Path

import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ...config import get_settings, load_brand_config
from ...db import PostRepository, init_db
from ...models import CarouselSlide
from ...render import RenderUnavailable, SlideRenderer, build_card_html, is_available
from ..ui import plain

app = typer.Typer(help="캐러셀 텍스트 카드 렌더링 (HTML → PNG)")
console = Console()

# 대괄호가 rich 마크업으로 먹히지 않도록 출력 시 plain() 을 거친다
RENDER_INSTALL_CMD = "pip install -e '.[render]' && playwright install chromium"


def _report(rendered) -> None:
    table = Table(title=f"렌더링 완료 — {len(rendered)}장", box=box.ROUNDED)
    table.add_column("#", justify="right", width=3)
    table.add_column("헤드라인", width=36)
    table.add_column("파일", width=34)
    for r in rendered:
        headline = r.headline if not r.oversized else f"[yellow]{r.headline}[/yellow]"
        table.add_row(str(r.index), headline[:36], r.path.name)
    console.print(table)
    if any(r.oversized for r in rendered):
        console.print(
            "[yellow]⚠ 노란색 헤드라인은 글자수 한도를 넘겨 카드에서 글씨가 작아집니다. "
            "brand/config.yaml 의 carousel.headline_max_chars 를 확인하세요.[/yellow]"
        )


@app.command("slides")
def render_slides(
    post_id: int = typer.Argument(..., help="렌더링할 게시물 ID"),
):
    """게시물의 캐러셀 슬라이드를 PNG로 렌더링."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    renderer = SlideRenderer(settings, brand)
    try:
        with console.status("[bold green]카드를 렌더링하고 있습니다...[/bold green]"):
            rendered = renderer.render_by_id(post_id)
    except RenderUnavailable as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)

    _report(rendered)
    console.print(f"[dim]저장 위치: {renderer.output_dir(post_id)}[/dim]")
    console.print(
        "[dim]발행하려면 이 PNG를 업로드해 공개 URL을 slide.image_url 에 채워야 합니다.[/dim]"
    )


@app.command("sample")
def render_sample(
    out: Path = typer.Option(Path("./sample_card.png"), "--out", "-o", help="저장 경로"),
    text: str = typer.Option(
        "6개월을 날린 자동화 실수", "--text", "-t", help="카드에 넣을 헤드라인"
    ),
    body: str = typer.Option(
        "도구를 늘릴수록 일이 줄어들 거라 믿었습니다.", "--body", "-b", help="보조 문구"
    ),
    emphasis: str = typer.Option("6개월", "--emphasis", "-e", help="강조할 문자열"),
):
    """샘플 카드 한 장을 렌더링 — 폰트·색상 확인용.

    한글이 깨지거나 네모로 나오면 실행 환경에 한글 폰트가 없는 것입니다
    (brand/config.yaml 의 carousel.font_family_css 참조).
    """
    settings = get_settings()
    brand = load_brand_config(settings.brand_config_path)
    slide = CarouselSlide(
        index=1, role="hook", headline=text, body=body,
        emphasis=[e for e in [emphasis] if e],
    )
    html = build_card_html(slide, brand, total=1)

    from ...render import render_html_to_png
    try:
        path = render_html_to_png(
            html, out, width=brand.carousel.width, height=brand.carousel.height
        )
    except RenderUnavailable as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓ 샘플 카드 저장:[/green] {path}")
    console.print(f"[dim]폰트 스택: {brand.carousel.font_family_css}[/dim]")
    console.print("[dim]한글이 네모(□)로 보이면 한글 폰트를 설치하세요.[/dim]")


@app.command("check")
def check_environment():
    """렌더링 환경 점검 (playwright/브라우저 사용 가능 여부)."""
    settings = get_settings()
    brand = load_brand_config(settings.brand_config_path)
    if is_available():
        console.print("[green]✓ playwright 사용 가능[/green]")
    else:
        console.print("[red]✗ playwright 미설치[/red]")
        console.print(f"  [bold]{plain(RENDER_INSTALL_CMD)}[/bold]")
        raise typer.Exit(1)
    console.print(f"[dim]캔버스: {brand.carousel.width}×{brand.carousel.height}[/dim]")
    console.print(f"[dim]폰트 스택: {brand.carousel.font_family_css}[/dim]")
    console.print("[dim]render sample 로 한글 렌더링을 눈으로 확인하세요.[/dim]")
