import typer
from rich.console import Console

from ...config import resolve_settings
from ...db import init_db
from ...diagnostics import Diagnostics

app = typer.Typer(help="연결 진단 (키·토큰·ID 검사)")
console = Console()

ICON = {"ok": "[green]✓[/green]", "warn": "[yellow]⚠[/yellow]",
        "fail": "[red]✗[/red]", "skip": "[dim]—[/dim]"}


@app.command("run")
def run_doctor(
    fix: bool = typer.Option(False, "--fix", help="탐색된 올바른 사용자 ID를 자동 저장"),
):
    """키·토큰·계정 연결이 실제로 동작하는지 검사하고 해결법을 안내합니다."""
    settings = resolve_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    with console.status("[bold green]연결을 진단하고 있습니다...[/bold green]"):
        checks = Diagnostics(settings).run_all(autofix=fix)

    console.print()
    for c in checks:
        console.print(f"{ICON.get(c.status, '•')} [bold]{c.name}[/bold] — {c.message}")
        if c.hint and c.status in ("warn", "fail"):
            console.print(f"    [dim]→ {c.hint}[/dim]")

    failed = [c for c in checks if c.status == "fail"]
    warned = [c for c in checks if c.status == "warn"]
    console.print()
    if failed:
        console.print(f"[red]{len(failed)}개 항목이 실패했습니다.[/red] 위 안내를 따라 수정하세요.")
        raise typer.Exit(1)
    if warned:
        console.print(
            f"[yellow]{len(warned)}개 경고가 있습니다.[/yellow] "
            "[bold]branding doctor run --fix[/bold] 로 자동 수정할 수 있습니다."
        )
        return
    console.print("[green]모든 검사 통과 — 생성·발행 준비 완료.[/green]")
