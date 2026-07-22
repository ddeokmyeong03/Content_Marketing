import typer
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box

from ...config import load_brand_config, get_settings

app = typer.Typer(help="브랜드 설정 관리")
console = Console()


@app.command("show")
def show_brand():
    """브랜드 정체성 설정 확인"""
    settings = get_settings()
    try:
        brand = load_brand_config(settings.brand_config_path)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold]{brand.persona.profession}[/bold]\n\n"
        f"[italic]{brand.persona.tagline_ko}[/italic]\n\n"
        f"{brand.persona.bio_ko.strip()}",
        title="브랜드 페르소나",
        border_style="blue",
    ))

    pillar_table = Table(title="콘텐츠 기둥", box=box.ROUNDED)
    pillar_table.add_column("ID", style="cyan")
    pillar_table.add_column("이름", style="white")
    pillar_table.add_column("비중", justify="right", style="green")
    pillar_table.add_column("설명")
    for p in brand.content_pillars:
        pillar_table.add_row(p.id, p.name_ko, f"{int(p.weight * 100)}%", p.description_ko)
    console.print(pillar_table)

    console.print(Panel(
        f"핵심 톤: [bold]{brand.tone_of_voice.primary}[/bold]\n"
        f"특성: {', '.join(brand.tone_of_voice.secondary)}\n"
        f"경어: {brand.tone_of_voice.korean_register}\n"
        f"피할 것: [red]{', '.join(brand.tone_of_voice.avoid)}[/red]",
        title="톤 오브 보이스",
        border_style="yellow",
    ))

    auto = brand.automation
    schedule = brand.posting_schedule
    console.print(Panel(
        f"Instagram: 주 {schedule.instagram.freq if hasattr(schedule.instagram, 'freq') else schedule.instagram.frequency}회  |  "
        f"Threads: 주 {schedule.threads.frequency}회\n"
        f"자동 승인: {'✓ 활성화' if auto.auto_approve else '✗ 비활성 (검토 필요)'}",
        title="발행 설정",
        border_style="green",
    ))
