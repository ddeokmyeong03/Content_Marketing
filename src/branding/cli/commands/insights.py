import typer
from rich.console import Console
from rich.table import Table
from rich import box

from ...analysis import BreakoutService
from ...config import get_settings, load_brand_config
from ...db import AccountMetricsRepository, BreakoutPatternRepository, MetricsRepository, init_db
from ...insights import InsightsService
from ...models.enums import Platform

app = typer.Typer(help="발행 성과 인사이트 수집 및 조회")
console = Console()


@app.command("sync")
def sync_insights():
    """발행 게시물 + 계정 성과를 Graph API로 수집·저장."""
    settings = get_settings()
    init_db(settings.db_path)
    with console.status("[bold green]인사이트를 수집하고 있습니다...[/bold green]"):
        posts, accounts = InsightsService(settings).sync_all()
    if not posts and not accounts:
        console.print("[dim]수집할 데이터가 없거나 지표를 가져오지 못했습니다.[/dim]")
        return
    if posts:
        console.print(f"[green]✓ {len(posts)}개 게시물 성과 수집[/green]")
        for m in posts:
            console.print(
                f"  #{m.post_id} [{m.platform.value}] "
                f"♥{m.likes} 💬{m.comments} 🔁{m.shares} 🔖{m.saved} "
                f"👤{m.follows} (참여율 {m.engagement_rate})"
            )
    if accounts:
        console.print(f"[green]✓ {len(accounts)}개 계정 스냅샷 수집[/green]")
        for a in accounts:
            console.print(f"  [{a.platform.value}] 팔로워 {a.followers_count} · 도달 {a.reach}")


@app.command("account")
def account_growth(
    days: int = typer.Option(30, "--days", "-d", help="성장 추이 기간(일)"),
):
    """계정 팔로워 스냅샷 및 성장 추이 (BGI 귀인의 기반)."""
    settings = get_settings()
    init_db(settings.db_path)
    repo = AccountMetricsRepository(settings.db_path)
    found = False
    for platform in (Platform.INSTAGRAM, Platform.THREADS):
        latest = repo.latest(platform)
        if not latest:
            continue
        found = True
        growth = repo.follower_growth(platform, days=days)
        growth_str = (
            f"[green]+{growth}[/green]" if growth and growth > 0
            else (str(growth) if growth is not None else "데이터 부족")
        )
        console.print(
            f"[cyan]{platform.value}[/cyan]: 팔로워 {latest.followers_count} "
            f"· 최근 {days}일 성장 {growth_str} "
            f"· 도달 {latest.reach} · 프로필뷰 {latest.profile_views}"
        )
    if not found:
        console.print("[dim]계정 스냅샷이 없습니다. branding insights sync 를 먼저 실행하세요.[/dim]")


@app.command("breakouts")
def breakouts(
    weeks: int = typer.Option(8, "--weeks", "-w", help="분석 기간(주)"),
    threshold: float = typer.Option(2.5, "--threshold", "-z", help="브레이크아웃 z 임계값"),
    all_posts: bool = typer.Option(False, "--all", help="브레이크아웃 외 전체 점수도 표시"),
):
    """팔로워 대비 압도적으로 뜬 게시물(브레이크아웃) 탐지."""
    settings = get_settings()
    init_db(settings.db_path)
    svc = BreakoutService(settings)
    rows = svc.analyze(weeks=weeks, z_threshold=threshold)
    if not all_posts:
        rows = [r for r in rows if r.result.is_breakout]
    if not rows:
        console.print(
            "[dim]브레이크아웃이 없습니다. 성과 데이터가 충분히 쌓였는지 "
            "(insights sync) 확인하세요.[/dim]"
        )
        return

    table = Table(title=f"브레이크아웃 (최근 {weeks}주, z≥{threshold})", box=box.ROUNDED)
    table.add_column("점수", justify="right", width=6)
    table.add_column("", width=3)
    table.add_column("플랫폼", width=9)
    table.add_column("주제", width=30)
    table.add_column("이상치 지표", width=28)
    for r in rows:
        flag = "🚀" if r.result.is_breakout else ""
        reasons = ", ".join(r.result.reasons) or "-"
        color = "green" if r.result.is_breakout else "dim"
        table.add_row(
            f"[{color}]{r.result.breakout_score}[/{color}]",
            flag,
            r.post.platform.value,
            (r.post.topic or "")[:28],
            reasons,
        )
    console.print(table)
    console.print(
        "[dim]이상치 지표: reach_rate(확산) · share_rate · follow_rate(성장) · "
        "save_rate · interaction_rate[/dim]"
    )


@app.command("attribution")
def attribution(
    days: int = typer.Option(30, "--days", "-d", help="귀인 기간(일)"),
    limit: int = typer.Option(10, "--limit", "-n", help="플랫폼별 표시 개수"),
):
    """계정 팔로워 성장을 게시물에 귀속 ('이 글이 데려온 팔로워')."""
    settings = get_settings()
    init_db(settings.db_path)
    groups = BreakoutService(settings).attribute_growth(days=days)
    if not groups:
        console.print("[dim]귀인할 데이터가 없습니다. insights sync 후 다시 시도하세요.[/dim]")
        return
    for g in groups:
        growth = "데이터 부족" if g.follower_growth is None else f"+{g.follower_growth}"
        console.print(
            f"\n[bold cyan]{g.platform.value}[/bold cyan] "
            f"— 최근 {days}일 팔로워 성장 [green]{growth}[/green]"
        )
        if g.follower_growth is None:
            console.print("  [dim]스냅샷이 2개 이상 쌓여야 귀인이 가능합니다.[/dim]")
            continue
        table = Table(box=box.SIMPLE)
        table.add_column("추정 유입", justify="right", width=8)
        table.add_column("방식", width=8)
        table.add_column("직접팔로우", justify="right", width=9)
        table.add_column("주제", width=36)
        for row in g.rows[:limit]:
            table.add_row(
                f"{row.result.attributed_followers}",
                row.result.method,
                str(row.result.direct_follows),
                (row.post.topic or "")[:34],
            )
        console.print(table)
    console.print(
        "\n[dim]direct=게시물 팔로우 지표 기반(IG) · modeled=상호작용 대리 분배(Threads)[/dim]"
    )


@app.command("deconstruct")
def deconstruct(
    weeks: int = typer.Option(8, "--weeks", "-w", help="분석 기간(주)"),
    limit: int = typer.Option(5, "--limit", "-n", help="이번에 분석할 최대 개수"),
):
    """브레이크아웃 게시물을 AI로 역설계해 '승리 공식'으로 저장."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        console.print("[red]ANTHROPIC_API_KEY 가 설정되지 않았습니다.[/red]")
        raise typer.Exit(1)
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    svc = BreakoutService(settings)
    with console.status("[bold green]브레이크아웃을 역설계하고 있습니다...[/bold green]"):
        patterns = svc.deconstruct_new(
            brand, settings.anthropic_api_key, weeks=weeks, limit=limit,
            model=settings.anthropic_model,
        )
    if not patterns:
        console.print("[dim]새로 역설계할 브레이크아웃이 없습니다. (insights breakouts로 확인)[/dim]")
        return
    console.print(f"[green]✓ {len(patterns)}개 승리 공식 도출[/green]")
    for p in patterns:
        console.print(Panel(
            f"[bold]훅 유형:[/bold] {p.hook_type}\n"
            f"[bold]심리 레버:[/bold] {', '.join(p.psychology_levers)}\n"
            f"[bold]확산 가설:[/bold] {p.spread_hypothesis}\n"
            f"[bold]재현 공식:[/bold] {p.replicable_formula}",
            title=f"승리 공식 (post #{p.post_id}, 신뢰도 {p.confidence})",
            border_style="magenta",
        ))


@app.command("patterns")
def patterns(limit: int = typer.Option(10, "--limit", "-n", help="표시 개수")):
    """저장된 승리 공식(역설계 결과) 확인."""
    settings = get_settings()
    init_db(settings.db_path)
    rows = BreakoutPatternRepository(settings.db_path).top(limit=limit)
    if not rows:
        console.print("[dim]저장된 승리 공식이 없습니다. branding insights deconstruct 를 실행하세요.[/dim]")
        return
    table = Table(title="승리 공식 라이브러리", box=box.ROUNDED)
    table.add_column("신뢰도", justify="right", width=6)
    table.add_column("훅 유형", width=16)
    table.add_column("심리 레버", width=24)
    table.add_column("재현 공식", width=40)
    for p in rows:
        table.add_row(
            str(p.confidence),
            p.hook_type,
            ", ".join(p.psychology_levers)[:22],
            (p.replicable_formula or "")[:38],
        )
    console.print(table)


@app.command("top")
def top_performers(
    weeks: int = typer.Option(8, "--weeks", "-w", help="조회 기간(주)"),
    limit: int = typer.Option(10, "--limit", "-n", help="상위 개수"),
):
    """참여율 상위 성과 콘텐츠 확인 (다음 기획에 재주입되는 학습 데이터)."""
    settings = get_settings()
    init_db(settings.db_path)
    brand = load_brand_config(settings.brand_config_path)
    repo = MetricsRepository(settings.db_path)
    rows = repo.top_performers(
        weeks=weeks, limit=limit, order_by=brand.engagement.primary_metric
    )
    if not rows:
        console.print("[dim]성과 데이터가 없습니다. 먼저 branding insights sync 를 실행하세요.[/dim]")
        return

    table = Table(
        title=f"상위 성과 콘텐츠 (기준: {brand.engagement.primary_metric})", box=box.ROUNDED
    )
    table.add_column("기둥", width=16)
    table.add_column("주제", width=34)
    table.add_column("채택 훅", width=34)
    table.add_column("참여율", justify="right", width=8)
    for r in rows:
        table.add_row(
            r["pillar"],
            (r["topic"] or "")[:32],
            (r["chosen_hook"] or "-")[:32],
            f"{r['engagement_rate']}",
        )
    console.print(table)
