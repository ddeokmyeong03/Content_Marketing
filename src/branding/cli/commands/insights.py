import typer
from rich.console import Console
from rich.table import Table
from rich import box

from ...config import get_settings, load_brand_config
from ...db import MetricsRepository, init_db
from ...insights import InsightsService

app = typer.Typer(help="발행 성과 인사이트 수집 및 조회")
console = Console()


@app.command("sync")
def sync_insights():
    """발행된 게시물의 실제 성과를 Graph API로 수집·저장."""
    settings = get_settings()
    init_db(settings.db_path)
    with console.status("[bold green]인사이트를 수집하고 있습니다...[/bold green]"):
        collected = InsightsService(settings).sync()
    if not collected:
        console.print("[dim]수집할 발행 게시물이 없거나 지표를 가져오지 못했습니다.[/dim]")
        return
    console.print(f"[green]✓ {len(collected)}개 게시물 성과 수집 완료[/green]")
    for m in collected:
        console.print(
            f"  #{m.post_id} [{m.platform.value}] "
            f"♥{m.likes} 💬{m.comments} 🔁{m.shares} 🔖{m.saved} "
            f"(참여율 {m.engagement_rate})"
        )


@app.command("top")
def top_performers(
    weeks: int = typer.Option(8, "--weeks", "-w", help="조회 기간(주)"),
    limit: int = typer.Option(10, "--limit", "-n", help="상위 개수"),
):
    """참여율 상위 성과 콘텐츠 확인 (다음 기획에 재주입되는 학습 데이터)."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    repo = MetricsRepository(settings.db_path)
    rows = repo.top_performers(
        weeks=weeks, limit=limit, order_by=brand.engagement.primary_metric
    )
    if not rows:
        console.print("[dim]성과 데이터가 없습니다. 먼저 branding insights sync 를 실행하세요.[/dim]")
        return

    table = Table(
        title=f"상위 성과 콘텐츠 (기준: {brand.engagement.primary_metric})", box=box.ROUNDED
    )
    table.add_column("기둥", width=16)
    table.add_column("주제", width=34)
    table.add_column("채택 훅", width=34)
    table.add_column("참여율", justify="right", width=8)
    for r in rows:
        table.add_row(
            r["pillar"],
            (r["topic"] or "")[:32],
            (r["chosen_hook"] or "-")[:32],
            f"{r['engagement_rate']}",
        )
    console.print(table)
