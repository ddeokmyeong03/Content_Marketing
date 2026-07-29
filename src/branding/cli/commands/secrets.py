import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ...config import get_settings
from ...db import SettingsStore, TokenRepository, init_db
from ...security import (
    KEYFILE_NAME, SECRET_KEY_ENV, SecretBox, SecretsUnavailable, generate_key, is_encrypted,
)

app = typer.Typer(help="자격증명 암호화 관리")
console = Console()


@app.command("init")
def init_key():
    """새 마스터 키를 생성해 출력 (환경변수로 관리할 때 사용)."""
    console.print(f"[bold]{SECRET_KEY_ENV}[/bold]={generate_key()}")
    console.print(
        f"\n[dim]이 값을 .env 또는 배포 환경의 비밀 변수로 두세요. 설정하지 않으면 "
        f"데이터 디렉터리의 {KEYFILE_NAME} 파일이 자동 생성돼 사용됩니다.[/dim]"
    )
    console.print(
        "[yellow]키를 잃어버리면 저장된 키·토큰을 복호화할 수 없습니다. "
        "반드시 백업하세요.[/yellow]"
    )


@app.command("status")
def status():
    """저장된 자격증명의 암호화 상태 확인."""
    settings = get_settings()
    init_db(settings.db_path)
    store = SettingsStore(settings.db_path)

    try:
        box_ = SecretBox.for_db_path(settings.db_path)
    except SecretsUnavailable as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    source = (
        f"{SECRET_KEY_ENV} 환경변수"
        if __import__("os").environ.get(SECRET_KEY_ENV, "").strip()
        else f"{settings.data_dir / KEYFILE_NAME}"
    )
    if box_.enabled:
        console.print(f"[green]✓ 암호화 활성[/green] — 키 출처: {source}")
    else:
        console.print("[red]✗ 암호화 비활성 — 값이 평문으로 저장됩니다.[/red]")

    raw = store.raw_all()
    if not raw:
        console.print("[dim]웹에서 등록된 설정이 없습니다.[/dim]")
        return

    table = Table(title="설정 저장소", box=box.ROUNDED)
    table.add_column("키", width=28)
    table.add_column("상태", width=12)
    plaintext = 0
    for key, value in sorted(raw.items()):
        if is_encrypted(value):
            table.add_row(key, "[green]암호화됨[/green]")
        else:
            plaintext += 1
            table.add_row(key, "[yellow]평문[/yellow]")
    console.print(table)
    if plaintext:
        console.print(
            f"[yellow]평문 {plaintext}건 — `branding secrets migrate` 로 암호화하세요.[/yellow]"
        )


@app.command("migrate")
def migrate():
    """기존에 평문으로 저장된 키·토큰을 암호화해 다시 쓴다."""
    settings = get_settings()
    init_db(settings.db_path)
    try:
        box_ = SecretBox.for_db_path(settings.db_path)
        if not box_.enabled:
            console.print("[red]암호화를 사용할 수 없어 마이그레이션할 수 없습니다.[/red]")
            raise typer.Exit(1)
        changed_settings = SettingsStore(settings.db_path).reencrypt_all()
        changed_tokens = TokenRepository(settings.db_path).reencrypt_all()
    except SecretsUnavailable as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    total = len(changed_settings) + len(changed_tokens)
    if not total:
        console.print("[green]✓ 이미 모두 암호화돼 있습니다.[/green]")
        return
    console.print(f"[green]✓ {total}건 암호화 완료[/green]")
    for key in changed_settings:
        console.print(f"  설정: {key}")
    for platform in changed_tokens:
        console.print(f"  토큰: {platform}")
    console.print(
        f"[dim]키 파일({settings.data_dir / KEYFILE_NAME})을 잃어버리면 복호화할 수 "
        f"없습니다. 백업하세요.[/dim]"
    )
