import typer
from rich.console import Console

app = typer.Typer(help="운영 대시보드 (웹 UI)")
console = Console()


@app.command("run")
def run_web(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 호스트"),
    port: int = typer.Option(8000, "--port", "-p", help="포트"),
):
    """운영 대시보드 웹 서버 실행 (FastAPI + UI)."""
    try:
        import uvicorn
        from ...web import create_app
    except ImportError:
        console.print("[red]웹 의존성이 없습니다.[/red] 설치: [bold]pip install -e '.[web]'[/bold]")
        raise typer.Exit(1)

    console.print(f"[bold green]대시보드 실행:[/bold green] http://{host}:{port}")
    console.print("  [dim]Ctrl+C 로 종료[/dim]")
    uvicorn.run(create_app(), host=host, port=port, log_level="info")
