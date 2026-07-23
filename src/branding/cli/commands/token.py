from datetime import timedelta
from typing import Optional

import typer
from rich.console import Console

from ...config import get_settings
from ...db import TokenRepository, init_db
from ...models.enums import Platform
from ...utils.time import now_utc

app = typer.Typer(help="Meta/Threads 액세스 토큰 관리")
console = Console()

PLATFORM_CHOICES = [Platform.INSTAGRAM.value, Platform.THREADS.value]


@app.command("set")
def set_token(
    platform: str = typer.Option(..., "--platform", "-p", help=f"플랫폼: {PLATFORM_CHOICES}"),
    token: str = typer.Option(..., "--token", "-t", help="롱리브드 액세스 토큰"),
    expires_days: Optional[int] = typer.Option(
        60, "--expires-days", help="만료까지 남은 일수 (기본 60)"
    ),
):
    """토큰을 DB(token_store)에 저장. .env 값보다 우선 사용됩니다."""
    if platform not in PLATFORM_CHOICES:
        console.print(f"[red]알 수 없는 플랫폼: {platform}[/red]")
        raise typer.Exit(1)
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    repo = TokenRepository(settings.db_path)
    expires_at = now_utc() + timedelta(days=expires_days) if expires_days else None
    repo.upsert(platform, token, expires_at=expires_at)
    console.print(f"[green]✓ {platform} 토큰 저장됨[/green]")
    if expires_at:
        console.print(f"  만료 예정: {expires_at.strftime('%Y-%m-%d')}")


@app.command("show")
def show_tokens():
    """저장된 토큰 상태 확인 (토큰 값은 마스킹)."""
    settings = get_settings()
    init_db(settings.db_path)
    repo = TokenRepository(settings.db_path)
    found = False
    for p in PLATFORM_CHOICES:
        tok = repo.get_token(p)
        if not tok:
            continue
        found = True
        exp = repo.get_expiry(p)
        masked = f"{tok[:6]}…{tok[-4:]}" if len(tok) > 12 else "****"
        exp_str = exp.strftime("%Y-%m-%d") if exp else "미지정"
        console.print(f"[cyan]{p}[/cyan]: {masked}  (만료: {exp_str})")
    if not found:
        console.print("[dim]저장된 토큰이 없습니다. branding token set 으로 등록하세요.[/dim]")
