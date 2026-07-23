"""시간대 처리 유틸리티.

DB에는 항상 UTC(타임존 포함) ISO 문자열로 저장하고,
스케줄 계산은 브랜드 설정의 로컬 시간대(기본 Asia/Seoul)로 수행합니다.
`datetime.utcnow()`(deprecated, tz-naive)를 대체합니다.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")


def now_utc() -> datetime:
    """현재 시각을 타임존 포함 UTC로 반환."""
    return datetime.now(timezone.utc)


def to_utc(dt: datetime) -> datetime:
    """임의의 datetime을 UTC(aware)로 변환.

    tz-naive 값은 UTC로 간주합니다.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_dt(value: str | None) -> datetime | None:
    """ISO 문자열을 aware datetime으로 파싱. tz 정보가 없으면 UTC로 간주."""
    if not value:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def local_datetime(
    year: int, month: int, day: int, hour: int, minute: int, tz: str | ZoneInfo = KST
) -> datetime:
    """주어진 시간대의 로컬 시각을 aware datetime으로 생성."""
    zone = ZoneInfo(tz) if isinstance(tz, str) else tz
    return datetime(year, month, day, hour, minute, tzinfo=zone)
