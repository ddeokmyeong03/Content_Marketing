import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ...config import get_settings
from ...db import PostRepository, init_db
from ...upload import UploadError, UploadService, get_uploader
from ..ui import plain

app = typer.Typer(help="렌더된 카드를 공개 URL로 업로드 (Instagram 발행에 필요)")
console = Console()


@app.command("slides")
def upload_slides(
    post_id: int = typer.Argument(..., help="업로드할 게시물 ID"),
    force: bool = typer.Option(False, "--force", help="이미 URL이 있어도 다시 업로드"),
):
    """게시물의 렌더된 슬라이드를 업로드하고 image_url을 채운다."""
    settings = get_settings()
    init_db(settings.db_path)
    try:
        uploader = get_uploader(settings)
        with console.status("[bold green]업로드하고 있습니다...[/bold green]"):
            results = UploadService(settings, uploader).upload_by_id(post_id, force=force)
    except (UploadError, ValueError) as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)

    table = Table(title=f"업로드 완료 — {len(results)}장", box=box.ROUNDED)
    table.add_column("#", justify="right", width=3)
    table.add_column("공개 URL", width=62)
    table.add_column("", width=6)
    for r in results:
        table.add_row(str(r.index), r.url, "[dim]건너뜀[/dim]" if r.skipped else "[green]새로[/green]")
    console.print(table)
    console.print(f"[green]✓ 이제 발행할 수 있습니다:[/green] branding post now {post_id}")


@app.command("check")
def check_upload():
    """업로드 설정 점검."""
    settings = get_settings()
    try:
        uploader = get_uploader(settings)
        uploader.check()
    except UploadError as e:
        console.print(f"[red]✗ {plain(e)}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ 업로드 제공자 준비됨:[/green] {uploader.name}")
    console.print(f"[dim]경로 접두사: {settings.upload_prefix or '(없음)'}[/dim]")
    if settings.upload_public_base_url:
        console.print(f"[dim]공개 URL 접두사: {settings.upload_public_base_url}[/dim]")
    console.print(
        "[dim]⚠ Instagram이 이미지를 가져가려면 이 URL이 인증 없이 열려야 합니다.[/dim]"
    )


@app.command("status")
def upload_status(
    post_id: int = typer.Argument(..., help="확인할 게시물 ID"),
):
    """슬라이드별 렌더·업로드 상태 확인."""
    settings = get_settings()
    init_db(settings.db_path)
    post = PostRepository(settings.db_path).get_by_id(post_id)
    if post is None:
        console.print(f"[red]게시물 #{post_id}를 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    slides = post.content.ordered_slides()
    if not slides:
        console.print("[dim]캐러셀 슬라이드가 없습니다.[/dim]")
        return

    table = Table(title=f"#{post_id} 슬라이드 상태", box=box.ROUNDED)
    table.add_column("#", justify="right", width=3)
    table.add_column("역할", width=7)
    table.add_column("헤드라인", width=34)
    table.add_column("상태", width=12)
    for s in slides:
        if s.image_url:
            state = "[green]업로드됨[/green]"
        elif s.image_path:
            state = "[yellow]렌더됨[/yellow]"
        else:
            state = "[red]미렌더[/red]"
        table.add_row(str(s.index), s.role, (s.headline or "")[:34], state)
    console.print(table)

    if not all(s.image_url for s in slides):
        console.print("[dim]발행하려면 모든 슬라이드가 '업로드됨' 이어야 합니다.[/dim]")
