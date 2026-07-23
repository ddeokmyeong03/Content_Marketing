from datetime import datetime, timezone

from branding.utils.time import KST, local_datetime, now_utc, parse_dt, to_utc


def test_now_utc_is_aware():
    dt = now_utc()
    assert dt.tzinfo is not None
    assert dt.utcoffset().total_seconds() == 0


def test_to_utc_treats_naive_as_utc():
    naive = datetime(2026, 1, 1, 12, 0, 0)
    assert to_utc(naive) == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_local_datetime_kst_to_utc():
    # 09:00 KST == 00:00 UTC (KST = UTC+9)
    local = local_datetime(2026, 7, 22, 9, 0, tz=KST)
    assert to_utc(local) == datetime(2026, 7, 22, 0, 0, tzinfo=timezone.utc)


def test_parse_dt_roundtrip_and_none():
    dt = now_utc()
    assert parse_dt(dt.isoformat()) == dt
    assert parse_dt(None) is None
    # tz 없는 문자열은 UTC로 간주
    assert parse_dt("2026-07-22T00:00:00").tzinfo is not None
