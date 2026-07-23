from datetime import datetime
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ...config import get_settings
from ...models import PostStatus
from ...db import init_db, PostRepository

app = typer.Typer(help="발행 대기 큐 관리")
console = Console()

STATUS_COLORS = {
    "draft": "dim",
    "review": "yellow",
    "approved": "green",
    "scheduled": "cyan",
    "published": "blue",
    "failed": "red",
    "rejected": "red dim",
}


@app.command("list")
def list_queue(
    status: str = typer.Option("draft", "--status", "-s", help="필터 상태 (draft/approved/published/all)"),
):
    """발행 대기 큐 목록 확인"""
    settings = get_settings()
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)

    if status == "all":
        statuses = list(PostStatus)
    else:
        try:
            statuses = [PostStatus(status)]
        except ValueError:
            console.print(f"[red]알 수 없는 상태: {status}[/red]")
            raise typer.Exit(1)

    all_posts = []
    for s in statuses:
        all_posts.extend(repo.list_by_status(s))

    if not all_posts:
        console.print(f"[dim]'{status}' 상태의 게시물이 없습니다.[/dim]")
        return

    table = Table(title=f"게시물 큐 ({status})", box=box.ROUNDED)
    table.add_column("ID", style="bold", width=4)
    table.add_column("플랫폼", width=10)
    table.add_column("기둥", width=16)
    table.add_column("주제", width=30)
    table.add_column("상태", width=10)
    table.add_column("예약 시간", width=20)

    for post in all_posts:
        color = STATUS_COLORS.get(post.status.value, "white")
        scheduled = (
            post.scheduled_at.strftime("%m/%d %H:%M") if post.scheduled_at else "-"
        )
        table.add_row(
            str(post.id),
            post.platform.value,
            post.content_pillar.value,
            post.topic[:28] + ("…" if len(post.topic) > 28 else ""),
            f"[{color}]{post.status.value}[/{color}]",
            scheduled,
        )

    console.print(table)


@app.command("show")
def show_post(post_id: int = typer.Argument(..., help="게시물 ID")):
    """게시물 상세 내용 확인"""
    settings = get_settings()
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    post = repo.get_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} 게시물을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    color = STATUS_COLORS.get(post.status.value, "white")
    console.print(Panel(
        f"[bold]ID:[/bold] {post.id}  |  "
        f"[bold]플랫폼:[/bold] {post.platform.value}  |  "
        f"[bold]타입:[/bold] {post.media_type.value}  |  "
        f"[bold]상태:[/bold] [{color}]{post.status.value}[/{color}]",
        title=f"게시물 #{post.id}: {post.topic}",
        border_style="blue",
    ))
    if post.content.engagement_score is not None:
        score = post.content.engagement_score
        color = "green" if score >= 80 else ("yellow" if score >= 70 else "red")
        console.print(Panel(
            f"[{color}]참여 예측 점수: {score}/100[/{color}]"
            + (f"\n[dim]{post.content.engagement_notes}[/dim]" if post.content.engagement_notes else ""),
            title="참여 엔진 평가",
            border_style=color,
        ))

    console.print(Panel(post.content.caption_ko, title="캡션 (한국어)"))
    if post.content.caption_en:
        console.print(Panel(post.content.caption_en, title="Caption (English)", border_style="dim"))

    if post.content.chosen_hook:
        console.print(f"[bold green]채택 훅:[/bold green] {post.content.chosen_hook}")
    if post.content.hook_variants:
        console.print("[bold]훅 후보 (기법 · 예측점수):[/bold]")
        for i, hv in enumerate(sorted(post.content.hook_variants, key=lambda h: -h.predicted_score), 1):
            console.print(f"  {i}. [{hv.predicted_score:>3}] [dim]{hv.technique}[/dim] — {hv.text}")
    elif post.content.hooks:
        console.print("[bold]훅 옵션:[/bold]")
        for i, hook in enumerate(post.content.hooks, 1):
            console.print(f"  {i}. {hook}")
    console.print(f"\n[bold]CTA:[/bold] {post.content.cta}")
    hashtags = " ".join(
        f"#{t}" if not t.startswith("#") else t
        for t in post.content.hashtags_ko + post.content.hashtags_en
    )
    console.print(f"[bold]해시태그:[/bold] [cyan]{hashtags}[/cyan]")


@app.command("approve")
def approve_post(post_id: int = typer.Argument(..., help="승인할 게시물 ID")):
    """게시물 승인 (DRAFT/REVIEW → APPROVED)"""
    settings = get_settings()
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    post = repo.get_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} 게시물을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)
    if post.status not in (PostStatus.DRAFT, PostStatus.REVIEW):
        console.print(f"[yellow]이미 '{post.status.value}' 상태입니다.[/yellow]")
        raise typer.Exit(0)

    repo.update_status(post_id, PostStatus.APPROVED)
    console.print(f"[green]✓ 게시물 #{post_id} 승인됨[/green]  → 스케줄러가 예약 시간에 자동 발행합니다.")
    console.print(f"  즉시 발행: [bold]branding post now {post_id}[/bold]")


@app.command("reject")
def reject_post(
    post_id: int = typer.Argument(..., help="거절할 게시물 ID"),
    reason: Optional[str] = typer.Option(None, "--reason", "-r", help="거절 사유"),
):
    """게시물 거절 (DRAFT/REVIEW → REJECTED)"""
    settings = get_settings()
    init_db(settings.db_path)
    repo = PostRepository(settings.db_path)
    post = repo.get_by_id(post_id)
    if not post:
        console.print(f"[red]ID {post_id} 게시물을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)

    repo.update_status(post_id, PostStatus.REJECTED)
    msg = f"[yellow]✗ 게시물 #{post_id} 거절됨[/yellow]"
    if reason:
        msg += f"\n  사유: {reason}"
    console.print(msg)
