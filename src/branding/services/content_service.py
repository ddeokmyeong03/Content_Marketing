"""주간 콘텐츠 생성 파이프라인 (계획 → 캡션 → DB 저장).

CLI(`plan generate`)와 스케줄러(주간 자동 생성)가 공유합니다.
- 최근 4주 주제를 중복 방지용으로 자동 전달
- 예약 시각을 브랜드 설정의 시간대로 계산해 UTC(aware)로 저장
- automation.auto_approve 에 따라 초기 상태(DRAFT/APPROVED) 결정
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from ..ai import generate_caption, generate_optimized_caption, generate_weekly_plan
from ..config.brand_config import BrandConfig
from ..config.settings import Settings
from ..db import PlanRepository, PostRepository, init_db
from ..models import ContentPlan, Post, PostStatus
from ..models.enums import Platform
from ..utils.time import local_datetime, to_utc

logger = logging.getLogger("branding.services")


@dataclass
class WeekResult:
    plan: ContentPlan
    posts: list[Post] = field(default_factory=list)


def _platform_schedule(brand: BrandConfig, platform: Platform):
    if platform == Platform.THREADS:
        return brand.posting_schedule.threads
    return brand.posting_schedule.instagram


def _scheduled_at(brand: BrandConfig, platform: Platform, day: date, slot_index: int):
    """플랫폼 선호 시각 중 하나를 골라 tz-aware UTC 예약 시각 생성."""
    sched = _platform_schedule(brand, platform)
    times = sched.preferred_times or ["09:00"]
    hour, minute = map(int, times[slot_index % len(times)].split(":"))
    local = local_datetime(day.year, day.month, day.day, hour, minute, tz=sched.timezone)
    return to_utc(local)


def generate_week(
    settings: Settings,
    brand: BrandConfig,
    week_start: Optional[date] = None,
    with_captions: bool = True,
    optimize: bool = True,
    progress: Optional[Callable[[int, int, str], None]] = None,
) -> WeekResult:
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY 가 설정되지 않았습니다.")

    settings.data_dir.mkdir(parents=True, exist_ok=True)
    init_db(settings.db_path)
    plan_repo = PlanRepository(settings.db_path)
    post_repo = PostRepository(settings.db_path)

    recent = post_repo.recent_topics(weeks=4)
    plan = generate_weekly_plan(
        brand_config=brand,
        api_key=settings.anthropic_api_key,
        week_start=week_start,
        recent_topics=recent,
        model=settings.anthropic_model,
    )
    saved_plan = plan_repo.save(plan)

    if not with_captions:
        return WeekResult(plan=saved_plan)

    initial_status = (
        PostStatus.APPROVED if brand.automation.auto_approve else PostStatus.DRAFT
    )
    week_number = saved_plan.week_start.isocalendar().week
    posts: list[Post] = []
    slot_counter: dict[tuple[str, int], int] = {}

    for i, topic in enumerate(saved_plan.topics, 1):
        if progress:
            progress(i, len(saved_plan.topics), topic.topic)
        caption_fn = generate_optimized_caption if optimize else generate_caption
        content = caption_fn(
            brand_config=brand,
            api_key=settings.anthropic_api_key,
            topic=topic.topic,
            pillar=topic.pillar,
            platform=topic.platform,
            media_type=topic.media_type,
            week_theme=saved_plan.theme_ko,
            model=settings.anthropic_model,
        )
        post_day = saved_plan.week_start + timedelta(days=topic.day_offset)
        slot_key = (topic.platform.value, topic.day_offset)
        slot_index = slot_counter.get(slot_key, 0)
        slot_counter[slot_key] = slot_index + 1
        scheduled_at = _scheduled_at(brand, topic.platform, post_day, slot_index)

        post = Post(
            plan_id=saved_plan.id,
            platform=topic.platform,
            media_type=topic.media_type,
            content_pillar=topic.pillar,
            topic=topic.topic,
            content=content,
            status=initial_status,
            scheduled_at=scheduled_at,
            week_number=week_number,
        )
        posts.append(post_repo.save(post))

    logger.info("주간 콘텐츠 생성 완료: %d개 포스트 (상태 %s)", len(posts), initial_status.value)
    return WeekResult(plan=saved_plan, posts=posts)
