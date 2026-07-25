from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from ...config import load_brand_config, resolve_settings
from ...db import CommentRepository, init_db
from ...engagement import EngagementService
from ...models.enums import CommentStatus

app = typer.Typer(help="댓글 응대 (계정 활성화)")
console = Console()

STATUS_COLOR = {"new": "yellow", "drafted": "cyan", "replied": "green",
                "ignored": "dim", "failed": "red"}


@app.command("sync")
def sync_comments(
    draft: bool = typer.Option(True, "--draft/--no-draft", help="수집 후 AI 답글 초안 생성"),
):
    """내 게시물의 신규 댓글을 수집하고 답글 초안을 만듭니다."""
    settings = resolve_settings()
    init_db(settings.db_path)
    svc = EngagementService(settings)

    with console.status("[bold green]댓글을 수집하고 있습니다...[/bold green]"):
        new_comments = svc.sync_comments()
    console.print(f"[green]✓ 신규 댓글 {len(new_comments)}건[/green]")

    if draft and new_comments:
        if not settings.anthropic_api_key:
            console.print("[yellow]ANTHROPIC_API_KEY 가 없어 초안 생성을 건너뜁니다.[/yellow]")
            return
        brand = load_brand_config(settings.brand_config_path)
        with console.status("[bold green]답글 초안을 작성하고 있습니다...[/bold green]"):
            drafted = svc.draft_replies(brand, settings.anthropic_api_key,
                                        model=settings.anthropic_model)
        console.print(f"[cyan]✓ 초안 {len(drafted)}건 생성[/cyan] (스팸은 자동 무시)")
        console.print("  검토: [bold]branding engage list[/bold]")


@app.command("list")
def list_comments(
    status: str = typer.Option("drafted", "--status", "-s",
                               help="new/drafted/replied/ignored/failed/all"),
):
    """댓글 목록과 답글 초안 확인."""
    settings = resolve_settings()
    init_db(settings.db_path)
    repo = CommentRepository(settings.db_path)
    if status == "all":
        rows = repo.list_by_status(*list(CommentStatus))
    else:
        try:
            rows = repo.list_by_status(CommentStatus(status))
        except ValueError:
            console.print(f"[red]알 수 없는 상태: {status}[/red]")
            raise typer.Exit(1)
    if not rows:
        console.print(f"[dim]'{status}' 상태의 댓글이 없습니다.[/dim]")
        return

    table = Table(title=f"댓글 ({status})", box=box.ROUNDED)
    table.add_column("ID", width=4)
    table.add_column("플랫폼", width=9)
    table.add_column("작성자", width=14)
    table.add_column("댓글", width=32)
    table.add_column("답글 초안", width=32)
    table.add_column("상태", width=8)
    for c in rows:
        color = STATUS_COLOR.get(c.status.value, "white")
        table.add_row(
            str(c.id), c.platform.value, f"@{c.author}"[:13],
            (c.text or "")[:30], (c.draft_reply or "-")[:30],
            f"[{color}]{c.status.value}[/{color}]",
        )
    console.print(table)
    console.print("  답글 발행: [bold]branding engage reply <ID>[/bold]")


@app.command("reply")
def reply(
    comment_id: int = typer.Argument(..., help="댓글 ID"),
    message: Optional[str] = typer.Option(None, "--message", "-m",
                                          help="직접 작성한 답글 (미지정 시 초안 사용)"),
):
    """댓글에 답글을 발행합니다."""
    settings = resolve_settings()
    init_db(settings.db_path)
    repo = CommentRepository(settings.db_path)
    comment = repo.get_by_id(comment_id)
    if not comment:
        console.print(f"[red]댓글 #{comment_id} 를 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    with console.status("[bold green]답글을 발행하고 있습니다...[/bold green]"):
        outcome = EngagementService(settings).post_reply(comment, message=message)
    if outcome.success:
        console.print(f"[green]✓ 답글 발행 완료 (comment #{comment_id})[/green]")
    else:
        console.print(f"[red]✗ 실패:[/red] {outcome.error}")
        raise typer.Exit(1)


@app.command("ignore")
def ignore(comment_id: int = typer.Argument(..., help="무시할 댓글 ID")):
    """댓글을 응대 불필요로 표시합니다."""
    settings = resolve_settings()
    init_db(settings.db_path)
    CommentRepository(settings.db_path).mark_status(comment_id, CommentStatus.IGNORED)
    console.print(f"[dim]✓ 댓글 #{comment_id} 무시 처리[/dim]")


@app.command("auto")
def auto_reply():
    """초안이 준비된 모든 댓글에 일괄 답글 발행."""
    settings = resolve_settings()
    init_db(settings.db_path)
    outs = EngagementService(settings).reply_all_drafted()
    if not outs:
        console.print("[dim]발행할 초안이 없습니다.[/dim]")
        return
    ok = sum(1 for o in outs if o.success)
    console.print(f"[green]✓ {ok}/{len(outs)}건 답글 발행[/green]")
    for o in outs:
        if not o.success:
            console.print(f"  [red]✗ #{o.comment_id}:[/red] {o.error}")
