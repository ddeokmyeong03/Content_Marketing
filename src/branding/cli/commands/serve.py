import typer
from rich.console import Console

from ...config import get_settings
from ...publisher import PublishService
from ...scheduler import run as run_scheduler

app = typer.Typer(help="자동화 스케줄러 실행")
console = Console()


@app.command("run")
def serve_run():
    """스케줄러 데몬 실행 (발행 폴링 + 주간 계획 자동 생성)."""
    settings = get_settings()
    console.print("[bold green]브랜딩 자동화 스케줄러를 시작합니다...[/bold green]")
    console.print("  [dim]Ctrl+C 로 종료[/dim]")
    run_scheduler(settings)


@app.command("publish-once")
def publish_once():
    """예약 시각이 지난 승인 게시물을 즉시 1회 발행 (스케줄러 없이)."""
    settings = get_settings()
    service = PublishService(settings)
    outcomes = service.run_pending()
    if not outcomes:
        console.print("[dim]발행 대기 중인 게시물이 없습니다.[/dim]")
        return
    for o in outcomes:
        if o.success:
            link = o.result.permalink if o.result else ""
            console.print(f"[green]✓ #{o.post_id} 발행됨[/green] {link}")
        else:
            console.print(f"[red]✗ #{o.post_id} 실패:[/red] {o.error}")
