from datetime import datetime
import typer
from rich.console import Console
from rich.panel import Panel
from rich.columns import Columns
from rich import box

from ...config import load_brand_config, get_settings
from ...models import Post, Platform, MediaType, ContentPillar, PostStatus
from ...db import init_db, PostRepository
from ...ai import generate_caption

app = typer.Typer(help="게시물 생성 및 관리")
console = Console()

PILLAR_CHOICES = [p.value for p in ContentPillar]
PLATFORM_CHOICES = [p.value for p in Platform if p != Platform.BOTH]
MEDIA_CHOICES = [m.value for m in MediaType]


@app.command("generate")
def generate_post(
    topic: str = typer.Option(..., "--topic", "-t", help="포스트 주제"),
    platform: str = typer.Option("instagram", "--platform", "-p", help=f"플랫폼: {PLATFORM_CHOICES}"),
    pillar: str = typer.Option("startup_reality", "--pillar", help=f"콘텐츠 기둥: {PILLAR_CHOICES}"),
    media_type: str = typer.Option("image", "--media-type", "-m", help=f"미디어 타입: {MEDIA_CHOICES}"),
    save: bool = typer.Option(True, "--save/--no-save", help="DB에 저장 여부"),
):
    """AI로 포스트 캡션 생성"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.[/red]")
        console.print("  .env 파일에 ANTHROPIC_API_KEY=your_key 를 추가하세요.")
        raise typer.Exit(1)

    try:
        brand = load_brand_config(settings.brand_config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    platform_enum = Platform(platform)
    pillar_enum = ContentPillar(pillar)
    media_enum = MediaType(media_type)

    with console.status(f"[bold green]Claude가 '{topic}' 캡션을 생성하고 있습니다...[/bold green]"):
        content = generate_caption(
            brand_config=brand,
            api_key=settings.anthropic_api_key,
            topic=topic,
            pillar=pillar_enum,
            platform=platform_enum,
            media_type=media_enum,
        )

    # 결과 출력
    console.print(Panel(
        content.caption_ko,
        title=f"[bold]캡션 (한국어) — {platform} / {media_type}[/bold]",
        border_style="blue",
    ))

    if content.caption_en:
        console.print(Panel(content.caption_en, title="Caption (English)", border_style="dim"))

    if content.hooks:
        hooks_text = "\n".join(f"  {i+1}. {h}" for i, h in enumerate(content.hooks))
        console.print(Panel(hooks_text, title="훅 옵션 (3가지)", border_style="yellow"))

    if content.cta:
        console.print(f"[bold]CTA:[/bold] {content.cta}")

    hashtags_ko = " ".join(f"#{t}" if not t.startswith("#") else t for t in content.hashtags_ko)
    hashtags_en = " ".join(f"#{t}" if not t.startswith("#") else t for t in content.hashtags_en)
    console.print(Panel(
        f"[cyan]{hashtags_ko}[/cyan]\n{hashtags_en}",
        title="해시태그",
        border_style="green",
    ))

    if content.image_brief:
        brief = content.image_brief
        console.print(Panel(
            f"[bold]장면:[/bold] {brief.description}\n"
            f"[bold]스타일:[/bold] {brief.style_notes}\n"
            f"[bold]Midjourney:[/bold] {brief.midjourney_prompt}",
            title="이미지 브리프",
            border_style="magenta",
        ))

    if save:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        init_db(settings.db_path)
        repo = PostRepository(settings.db_path)
        post = Post(
            platform=platform_enum,
            media_type=media_enum,
            content_pillar=pillar_enum,
            topic=topic,
            content=content,
            status=PostStatus.DRAFT,
            week_number=datetime.now().isocalendar().week,
        )
        saved = repo.save(post)
        console.print(f"\n[green]✓ DB에 저장됨 (ID: {saved.id}, 상태: DRAFT)[/green]")
        console.print(f"  승인하려면: [bold]branding queue approve {saved.id}[/bold]")
