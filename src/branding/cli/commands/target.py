import typer
from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ...config import get_settings, load_brand_config
from ...db import HashtagQuotaRepository, TargetRepository, init_db
from ...discovery import DiscoveryService
from ...models import TargetKind, TargetStatus
from ...publisher.base import MetaAPIError
from ..ui import plain

app = typer.Typer(help="타깃 발굴 — 반응할 게시물·계정 찾기 (실행은 사람이)")
console = Console()

TOS_NOTE = (
    "[dim]※ 팔로우·좋아요·댓글은 직접 하세요. 자동화는 플랫폼 정책 위반으로 "
    "계정 정지 위험이 있습니다.[/dim]"
)


def _table(rows, title: str) -> Table:
    table = Table(title=title, box=box.ROUNDED)
    table.add_column("ID", justify="right", width=4)
    table.add_column("점수", justify="right", width=5)
    table.add_column("종류", width=7)
    table.add_column("출처", width=14)
    table.add_column("내용", width=34)
    table.add_column("반응", width=14)
    for c in rows:
        if c.kind == TargetKind.ACCOUNT:
            content = f"@{c.username}"
            stats = f"팔로워 {c.followers_count}"
        else:
            content = (c.caption_excerpt or "(캡션 없음)").replace("\n", " ")[:34]
            stats = f"♥{c.like_count} 💬{c.comments_count}"
        color = "green" if c.score >= 60 else "yellow" if c.score >= 35 else "dim"
        table.add_row(
            str(c.id), f"[{color}]{c.score}[/{color}]", c.kind.value,
            c.source[:14], content, stats,
        )
    return table


@app.command("discover")
def discover(
    limit: int = typer.Option(25, "--limit", "-n", help="해시태그당 가져올 게시물 수"),
):
    """공식 읽기 전용 API로 반응 대상을 발굴해 저장."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    svc = DiscoveryService(settings, brand)

    if not svc.hashtags() and not brand.discovery.seed_accounts:
        console.print(
            "[yellow]탐색할 해시태그도 시드 계정도 없습니다.[/yellow]\n"
            "brand/config.yaml 의 [bold]discovery.hashtags[/bold] 또는 "
            "[bold]discovery.seed_accounts[/bold] 를 채우세요."
        )
        raise typer.Exit(1)

    try:
        with console.status("[bold green]타깃을 발굴하고 있습니다...[/bold green]"):
            report = svc.discover(limit_per_hashtag=limit)
    except MetaAPIError as e:
        console.print(f"[red]{plain(e)}[/red]")
        raise typer.Exit(1)

    if report.hashtags_queried:
        console.print(f"[dim]조회한 해시태그: {', '.join(report.hashtags_queried)}[/dim]")
    if report.hashtags_skipped:
        console.print(
            f"[yellow]⚠ 주간 한도로 건너뜀: {', '.join(report.hashtags_skipped)}[/yellow]"
        )
    console.print(f"[dim]남은 주간 해시태그 여유: {report.quota_remaining}개[/dim]")
    for err in report.errors:
        console.print(f"[red]· {err}[/red]")

    if not report.candidates:
        console.print("[dim]새로 발굴된 후보가 없습니다.[/dim]")
        return
    console.print(_table(report.candidates[:20], f"발굴 결과 {len(report.candidates)}건"))
    console.print("[dim]오늘 할 일은 `branding target checklist` 로 확인하세요.[/dim]")


@app.command("checklist")
def checklist(
    size: int = typer.Option(None, "--size", "-n", help="목록 크기 (기본: config)"),
):
    """오늘 실행할 목록 — 점수 높은 순."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    rows = DiscoveryService(settings, brand).checklist(size)

    if not rows:
        console.print(
            "[dim]실행 대기 중인 타깃이 없습니다. `branding target discover` 를 먼저 실행하세요.[/dim]"
        )
        return

    console.print(Panel(
        "\n".join(
            f"[bold]{i}.[/bold] {c.permalink or '@' + (c.username or '')}\n"
            f"   [dim]{', '.join(c.reasons) or '—'}[/dim]\n"
            f"   [dim]완료: branding target done {c.id}[/dim]"
            for i, c in enumerate(rows, 1)
        ),
        title=f"오늘의 실행 목록 ({len(rows)}건)",
        border_style="green",
    ))
    console.print(TOS_NOTE)


@app.command("list")
def list_targets(
    status: str = typer.Option("new", "--status", "-s", help="new | actioned | skipped"),
    limit: int = typer.Option(30, "--limit", "-n"),
):
    """발굴된 타깃 조회."""
    settings = get_settings()
    init_db(settings.db_path)
    try:
        target_status = TargetStatus(status)
    except ValueError:
        console.print(f"[red]알 수 없는 상태: {status}[/red]")
        raise typer.Exit(1)

    repo = TargetRepository(settings.db_path)
    rows = repo.list_by_status(target_status, limit=limit)
    if not rows:
        console.print(f"[dim]'{status}' 상태인 타깃이 없습니다.[/dim]")
        return
    console.print(_table(rows, f"타깃 ({status}) {len(rows)}건"))
    counts = repo.counts()
    console.print(
        "[dim]" + " · ".join(f"{k}: {v}" for k, v in sorted(counts.items())) + "[/dim]"
    )


def _mark(candidate_id: int, status: TargetStatus, note: str, verb: str) -> None:
    settings = get_settings()
    init_db(settings.db_path)
    updated = TargetRepository(settings.db_path).set_status(candidate_id, status, note)
    if updated is None:
        console.print(f"[red]타깃 #{candidate_id}를 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)
    console.print(f"[green]✓ #{candidate_id} {verb}[/green]")


@app.command("done")
def mark_done(
    candidate_id: int = typer.Argument(..., help="타깃 ID"),
    note: str = typer.Option("", "--note", help="메모 (무엇을 했는지)"),
):
    """직접 반응을 완료한 타깃 표시."""
    _mark(candidate_id, TargetStatus.ACTIONED, note, "실행 완료")


@app.command("skip")
def mark_skip(
    candidate_id: int = typer.Argument(..., help="타깃 ID"),
    note: str = typer.Option("", "--note", help="건너뛴 이유"),
):
    """적합하지 않은 타깃 건너뛰기."""
    _mark(candidate_id, TargetStatus.SKIPPED, note, "건너뜀")


@app.command("quota")
def quota():
    """해시태그 검색 주간 한도 확인 (7일 고유 30개)."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    repo = HashtagQuotaRepository(
        settings.db_path, limit=brand.discovery.max_hashtag_queries_per_week
    )
    used = sorted(repo.recent_unique())
    console.print(f"최근 7일 조회: [bold]{len(used)}[/bold] / {repo.limit}개")
    console.print(f"남은 여유: [bold]{repo.remaining()}[/bold]개")
    if used:
        console.print(f"[dim]조회한 해시태그: {', '.join(used)}[/dim]")
    console.print(
        "[dim]이미 조회한 해시태그를 다시 보는 것은 한도를 쓰지 않습니다.[/dim]"
    )
