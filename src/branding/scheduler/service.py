"""APScheduler 기반 자동화 데몬.

잡:
  1) publish-poll : N분마다 예약 시각이 지난 승인 게시물을 발행
  2) weekly-plan  : 매주 지정 요일/시각에 다음 주 콘텐츠 자동 생성
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from ..config import get_settings, load_brand_config
from ..config.settings import Settings
from ..db import init_db
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
    except Exception:
        logger.exception("주간 계획 잡 실행 중 오류")


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
        next_run_time=None,
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
    return scheduler


def run(settings: Settings | None = None) -> None:
    settings = settings or get_settings()
    scheduler = build_scheduler(settings)
    logger.info(
        "스케줄러 시작 — 발행 폴링 %d분 주기, 주간 계획 %s %02d:00 (%s)",
        settings.publish_poll_minutes,
        settings.weekly_plan_cron_day,
        settings.weekly_plan_cron_hour,
        settings.scheduler_timezone,
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("스케줄러 종료")
