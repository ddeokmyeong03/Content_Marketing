import typer
from rich import box
from rich.console import Console
from rich.table import Table

from ...config import get_settings
from ...db import SettingsStore, TokenRepository, init_db
from ...security import (
    KEYFILE_NAME, SECRET_KEY_ENV, SecretBox, SecretsUnavailable, env_key, generate_key,
    is_encrypted, read_keyfile, rotate_secrets, rotation_preview, write_keyfile,
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
        if env_key()
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


@app.command("rotate")
def rotate(
    old_key: str = typer.Option(
        "", "--old-key",
        help="현재 저장된 값을 복호화할 키. 생략하면 지금 쓰는 키(환경변수 또는 키 파일).",
    ),
    new_key: str = typer.Option(
        "", "--new-key", help="새로 쓸 키. 생략하면 새로 생성한다.",
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="확인 프롬프트 건너뛰기"),
):
    """마스터 키를 교체한다 — 저장된 키·토큰을 옛 키로 읽어 새 키로 다시 암호화.

    DB를 먼저 바꾸고, 성공한 뒤에 키 파일을 갱신한다. 실패하면 아무것도 바뀌지 않아
    옛 키로 계속 쓸 수 있다.
    """
    settings = get_settings()
    init_db(settings.db_path)

    from_env = bool(env_key())
    current = env_key() or read_keyfile(settings.data_dir)
    old = old_key.strip() or current or ""
    if not old:
        console.print(
            "[yellow]현재 키를 찾을 수 없습니다.[/yellow] 저장된 값이 평문이면 그대로 "
            "진행되고, 암호화돼 있다면 `--old-key` 로 옛 키를 알려주세요."
        )

    try:
        old_box = SecretBox(old) if old else SecretBox(None)
        new_plain = new_key.strip() or generate_key()
        new_box = SecretBox(new_plain)
    except SecretsUnavailable as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    if new_plain == old:
        console.print("[red]새 키가 옛 키와 같습니다 — 교체할 이유가 없습니다.[/red]")
        raise typer.Exit(1)

    n_settings, n_tokens = rotation_preview(settings.db_path)
    console.print(
        f"로테이션 대상: 설정 [bold]{n_settings}[/bold]건, 토큰 [bold]{n_tokens}[/bold]건"
    )
    if not yes and not typer.confirm("새 키로 다시 암호화할까요?", default=False):
        console.print("[dim]취소했습니다 — 아무것도 바뀌지 않았습니다.[/dim]")
        raise typer.Exit(0)

    # 1) DB 먼저. 여기서 실패하면 롤백되어 옛 키 그대로다.
    try:
        result = rotate_secrets(settings.db_path, old_box, new_box)
    except SecretsUnavailable as e:
        console.print(f"[red]로테이션 실패 — 되돌렸습니다.[/red]\n{e}")
        console.print(
            "[dim]옛 키가 맞는지 확인하세요. 저장된 값은 그대로입니다.[/dim]"
        )
        raise typer.Exit(1)

    console.print(f"[green]✓ DB 재암호화 완료 — {result.total}건[/green]")
    if result.encrypted_from_plaintext:
        console.print(
            f"[dim]  이 중 {result.encrypted_from_plaintext}건은 평문이던 값입니다.[/dim]"
        )

    # 2) DB가 새 키로 바뀐 뒤에야 키를 갱신한다. 순서가 반대면
    #    중간에 죽었을 때 DB는 옛 키, 파일은 새 키가 되어 못 읽는다.
    if from_env:
        # 환경변수는 프로세스 밖의 것이라 대신 바꿔줄 수 없다 — 반드시 사람이 해야 한다
        console.print(
            f"\n[bold yellow]⚠ {SECRET_KEY_ENV} 환경변수를 지금 아래 값으로 "
            f"바꾸세요.[/bold yellow] 바꾸기 전까지 저장된 자격증명을 읽을 수 없습니다."
        )
        console.print(f"\n[bold]{SECRET_KEY_ENV}[/bold]={new_plain}\n")
    else:
        try:
            path = write_keyfile(settings.data_dir, new_plain)
            console.print(f"[green]✓ 키 파일 갱신 — {path}[/green]")
        except OSError as e:
            # DB는 이미 새 키다. 키를 못 남겼으면 사람이 받아 적어야 한다.
            console.print(
                f"[bold red]⚠ 키 파일을 쓰지 못했습니다 ({e}).[/bold red] DB는 이미 "
                f"아래 키로 암호화됐습니다 — 지금 안전한 곳에 보관하세요."
            )
            console.print(f"\n[bold]{SECRET_KEY_ENV}[/bold]={new_plain}\n")
            raise typer.Exit(1)

    console.print(
        "[dim]옛 키는 이제 쓸모가 없습니다. 백업본이 있다면 폐기하세요. "
        "DB 백업본은 여전히 옛 키로 암호화돼 있으니 함께 관리하세요.[/dim]"
    )
