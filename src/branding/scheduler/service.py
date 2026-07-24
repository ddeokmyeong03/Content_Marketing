"""APScheduler 기반 자동화 데몬.

잡:
  1) publish-poll     : N분마다 예약 시각이 지난 승인 게시물을 발행
  2) weekly-plan      : 매주 지정 요일/시각에 다음 주 콘텐츠 자동 생성
  3) review-reminder  : (auto_approve=false일 때) 매일 검토 대기 게시물 알림
  4) token-refresh    : 매일 만료 임박 토큰 자동 갱신
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..auth import TokenRefresher
from ..config import get_settings, load_brand_config
from ..config.settings import Settings
from ..db import PostRepository, init_db
from ..insights import InsightsService
from ..models import PostStatus
from ..notify import get_notifier
from ..publisher import PublishService
from ..services import generate_week

logger = logging.getLogger("branding.scheduler")


def _publish_job(settings: Settings) -> None:
    try:
        PublishService(settings).run_pending()
    except Exception:  # 잡이 죽지 않도록 방어
        logger.exception("발행 잡 실행 중 오류")


def _weekly_plan_job(settings: Settings) -> None:
    try:
        brand = load_brand_config(settings.brand_config_path)
        # 다음 주 월요일 기준으로 생성
        today = date.today()
        next_monday = today + timedelta(days=(7 - today.weekday()))
        result = generate_week(settings, brand, week_start=next_monday, with_captions=True)
        logger.info("주간 계획 자동 생성: %d개 포스트", len(result.posts))
        get_notifier(settings).info(
            "주간 계획 자동 생성 완료",
            f"{result.plan.theme_ko} — {len(result.posts)}개 포스트",
        )
    except Exception:
        logger.exception("주간 계획 잡 실행 중 오류")


def _review_reminder_job(settings: Settings) -> None:
    try:
        repo = PostRepository(settings.db_path)
        pending = repo.list_by_status(PostStatus.DRAFT) + repo.list_by_status(PostStatus.REVIEW)
        if not pending:
            return
        lines = [f"  #{p.id} [{p.platform.value}] {p.topic[:40]}" for p in pending[:10]]
        get_notifier(settings).warning(
            f"검토 대기 게시물 {len(pending)}건",
            "\n".join(lines) + "\n\n승인: branding queue approve <id>",
        )
    except Exception:
        logger.exception("검토 리마인더 잡 실행 중 오류")


def _token_refresh_job(settings: Settings) -> None:
    try:
        results = TokenRefresher(settings).refresh_all_if_needed()
        refreshed = [r.platform for r in results if r.refreshed]
        if refreshed:
            get_notifier(settings).info("토큰 갱신됨", ", ".join(refreshed))
    except Exception:
        logger.exception("토큰 갱신 잡 실행 중 오류")


def _insights_sync_job(settings: Settings) -> None:
    try:
        posts, accounts = InsightsService(settings).sync_all()
        logger.info("인사이트 수집: 게시물 %d개, 계정 %d개", len(posts), len(accounts))
    except Exception:
        logger.exception("인사이트 수집 잡 실행 중 오류")


def build_scheduler(settings: Settings | None = None) -> BlockingScheduler:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)

    scheduler = BlockingScheduler(timezone=settings.scheduler_timezone)

    scheduler.add_job(
        _publish_job,
        trigger=IntervalTrigger(minutes=settings.publish_poll_minutes),
        args=[settings],
        id="publish-poll",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _weekly_plan_job,
        trigger=CronTrigger(
            day_of_week=settings.weekly_plan_cron_day,
            hour=settings.weekly_plan_cron_hour,
            minute=0,
        ),
        args=[settings],
        id="weekly-plan",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _token_refresh_job,
        trigger=CronTrigger(hour=settings.token_refresh_hour, minute=0),
        args=[settings],
        id="token-refresh",
        max_instances=1,
        coalesce=True,
    )

    scheduler.add_job(
        _insights_sync_job,
        trigger=CronTrigger(hour=settings.insights_sync_hour, minute=0),
        args=[settings],
        id="insights-sync",
        max_instances=1,
        coalesce=True,
    )

    # 검토 리마인더는 수동 승인 모드(auto_approve=false)에서만 등록
    try:
        brand = load_brand_config(settings.brand_config_path)
        if not brand.automation.auto_approve:
            scheduler.add_job(
                _review_reminder_job,
                trigger=CronTrigger(hour=brand.automation.review_reminder_hour, minute=0),
                args=[settings],
                id="review-reminder",
                max_instances=1,
                coalesce=True,
            )
    except FileNotFoundError:
        logger.warning("브랜드 설정을 찾을 수 없어 검토 리마인더 잡을 건너뜁니다.")

    return scheduler


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    scheduler = build_scheduler(settings)
    logger.info(
        "스케줄러 시작 — 발행 폴링 %d분, 주간 계획 %s %02d:00, 토큰 갱신 매일 %02d:00 (%s)",
        settings.publish_poll_minutes,
        settings.weekly_plan_cron_day,
        settings.weekly_plan_cron_hour,
        settings.token_refresh_hour,
        settings.scheduler_timezone,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")
