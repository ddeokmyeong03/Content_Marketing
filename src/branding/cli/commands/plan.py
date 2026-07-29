from datetime import date
from typing import Optional
import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ...config import load_brand_config, get_settings
from ...db import init_db, PlanRepository
from ...services import generate_week
from ..ui import plain

app = typer.Typer(help="주간 콘텐츠 계획 관리")
console = Console()

DAY_NAMES = ["월", "화", "수", "목", "금", "토", "일"]


@app.command("generate")
def generate_plan(
    week_start: Optional[str] = typer.Option(
        None, "--week", "-w", help="주 시작일 (YYYY-MM-DD, 기본: 이번 주 월요일)"
    ),
    captions: bool = typer.Option(False, "--captions/--no-captions", help="계획 생성 후 캡션도 바로 생성"),
):
    """AI로 주간 콘텐츠 캘린더 생성"""
    settings = get_settings()
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.[/red]")
        raise typer.Exit(1)

    try:
        brand = load_brand_config(settings.brand_config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)

    start_date = None
    if week_start:
        try:
            start_date = date.fromisoformat(week_start)
        except ValueError:
            console.print("[red]날짜 형식 오류. YYYY-MM-DD 형식으로 입력하세요.[/red]")
            raise typer.Exit(1)

    status_msg = (
        "[bold green]주간 계획 + 캡션을 생성하고 있습니다...[/bold green]"
        if captions
        else "[bold green]주간 콘텐츠 계획을 생성하고 있습니다...[/bold green]"
    )
    with console.status(status_msg):
        result = generate_week(
            settings=settings,
            brand=brand,
            week_start=start_date,
            with_captions=captions,
        )
    plan = result.plan

    console.print(Panel(
        f"[bold]{plan.theme_ko}[/bold]\n[dim]{plan.theme}[/dim]\n\n"
        f"{plan.week_start.strftime('%Y년 %m월 %d일')} ~ {plan.week_end.strftime('%m월 %d일')}",
        title=f"이번 주 테마 (계획 ID: {plan.id})",
        border_style="blue",
    ))

    table = Table(title="주간 콘텐츠 계획", box=box.ROUNDED)
    table.add_column("요일", width=4)
    table.add_column("플랫폼", width=10)
    table.add_column("기둥", width=16)
    table.add_column("주제", width=40)
    table.add_column("타입", width=10)

    for topic in sorted(plan.topics, key=lambda t: t.day_offset):
        table.add_row(
            DAY_NAMES[topic.day_offset],
            topic.platform.value,
            topic.pillar.value,
            topic.topic,
            topic.media_type.value,
        )
    console.print(table)

    if captions:
        for p in result.posts:
            console.print(f"  [green]✓[/green] #{p.id} [{p.status.value}] — {p.topic[:40]}")
        console.print(f"\n[green]총 {len(result.posts)}개 포스트 생성 완료.[/green]")
        if brand.automation.auto_approve:
            console.print("  [cyan]auto_approve 활성화 → 예약 시각에 자동 발행됩니다.[/cyan]")
        else:
            console.print("  검토하려면: [bold]branding queue list[/bold]")
    else:
        console.print("\n[dim]캡션을 생성하려면 --captions 옵션을 추가하세요.[/dim]")


@app.command("show")
def show_plan():
    """최근 주간 계획 확인"""
    settings = get_settings()
    init_db(settings.db_path)
    plan_repo = PlanRepository(settings.db_path)
    plan = plan_repo.get_latest()
    if not plan:
        console.print("[dim]저장된 계획이 없습니다. [bold]branding plan generate[/bold] 를 실행하세요.[/dim]")
        return

    console.print(Panel(
        f"[bold]{plan.theme_ko}[/bold]\n"
        f"{plan.week_start.strftime('%Y년 %m월 %d일')} ~ {plan.week_end.strftime('%m월 %d일')}",
        title=f"현재 계획 (ID: {plan.id})",
        border_style="blue",
    ))

    table = Table(box=box.SIMPLE)
    table.add_column("요일")
    table.add_column("플랫폼")
    table.add_column("주제")
    for topic in sorted(plan.topics, key=lambda t: t.day_offset):
        table.add_row(DAY_NAMES[topic.day_offset], topic.platform.value, topic.topic)
    console.print(table)
