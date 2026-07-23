import logging

import typer
from rich.console import Console
from rich.logging import RichHandler

from ..config import get_settings
from .commands import brand, post, queue, plan, serve, token, insights

app = typer.Typer(
    name="branding",
    help="인스타그램 & 쓰레드 브랜딩 자동 관리 서비스",
    no_args_is_help=True,
)
console = Console()

app.add_typer(brand.app, name="brand")
app.add_typer(post.app, name="post")
app.add_typer(queue.app, name="queue")
app.add_typer(plan.app, name="plan")
app.add_typer(serve.app, name="serve")
app.add_typer(token.app, name="token")
app.add_typer(insights.app, name="insights")


@app.callback()
def main():
    """브랜딩 자동화 서비스 CLI"""
    level = getattr(logging, get_settings().log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True, show_path=False)],
    )


if __name__ == "__main__":
    app()
