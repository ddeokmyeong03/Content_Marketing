import typer
from rich.console import Console

from ...config import get_settings
from ..ui import plain

app = typer.Typer(help="운영 대시보드 (웹 UI)")
console = Console()

# 대괄호가 rich 마크업으로 먹히지 않도록 출력 시 plain() 을 거친다
WEB_INSTALL_CMD = "pip install -e '.[web]'"


@app.command("run")
def run_web(
    host: str = typer.Option("127.0.0.1", "--host", help="바인드 호스트"),
    port: int = typer.Option(8000, "--port", "-p", help="포트"),
):
    """운영 대시보드 웹 서버 실행 (FastAPI + UI)."""
    # 웹 의존성만 따로 확인한다. 아래 `...web` import 는 앱 대부분을 끌어오므로,
    # 하나로 묶으면 엉뚱한 곳의 ImportError 까지 "웹 의존성 없음"으로 잘못 안내한다.
    for module, package in (("fastapi", "fastapi"), ("uvicorn", "uvicorn")):
        try:
            __import__(module)
        except ImportError:
            console.print(
                f"[red]웹 의존성이 없습니다[/red] — {package} 를 찾을 수 없습니다.\n"
                f"  설치: [bold]{plain(WEB_INSTALL_CMD)}[/bold]"
            )
            raise typer.Exit(1)

    import uvicorn

    from ...web import create_app
    from ...web.auth import is_loopback

    settings = get_settings()
    protected = bool((settings.web_auth_password or "").strip())

    # 이 대시보드는 키 등록·발행·승인이 가능한 운영 콘솔이다.
    # 인증 없이 기기 밖으로 열리는 경로를 아예 막는다.
    if not protected and not is_loopback(host):
        console.print(
            f"[red]인증 없이 외부에 노출할 수 없습니다 (host={host}).[/red]\n"
            "이 대시보드는 API 키 등록·발행·승인이 가능한 운영 콘솔입니다.\n"
            "  [bold]WEB_AUTH_PASSWORD[/bold] 를 설정하거나 "
            "[bold]--host 127.0.0.1[/bold] 로 실행하세요."
        )
        raise typer.Exit(1)

    console.print(f"[bold green]대시보드 실행:[/bold green] http://{host}:{port}")
    if protected:
        console.print(f"  [dim]인증: {settings.web_auth_user} (HTTP Basic)[/dim]")
    else:
        console.print("  [dim]인증 없음 — 이 기기에서만 접근 가능[/dim]")
    console.print("  [dim]Ctrl+C 로 종료[/dim]")
    uvicorn.run(create_app(settings), host=host, port=port, log_level="info")
