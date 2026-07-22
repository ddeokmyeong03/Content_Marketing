import typer
from rich.console import Console

from .commands import brand, post, queue, plan

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


@app.callback()
def main():
    """브랜딩 자동화 서비스 CLI"""
    pass


if __name__ == "__main__":
    app()
