"""Tests for app.utils.clock and the UTCDateTime column type."""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.models.models import Category, ZReport
from app.utils.clock import format_local, local_days_range, to_local, utc_now


def test_utc_now_is_aware_utc():
    now = utc_now()
    assert now.tzinfo is timezone.utc


def test_to_local_refuses_naive():
    with pytest.raises(ValueError):
        to_local(datetime(2026, 1, 1, 12))


def test_format_local_shows_local_wall_clock(brussels_tz):
    winter = datetime(2026, 1, 15, 11, 0, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 11, 0, tzinfo=timezone.utc)
    assert format_local(winter, "%H:%M") == "12:00"
    assert format_local(summer, "%H:%M") == "13:00"
    assert format_local(None, "%H:%M", empty="/") == "/"


def test_local_days_range_covers_local_midnight_to_midnight(brussels_tz):
    since, until = local_days_range(date(2026, 3, 1), date(2026, 3, 31))
    assert since == datetime(2026, 2, 28, 23, 0, tzinfo=timezone.utc)   # CET
    assert until == datetime(2026, 3, 31, 22, 0, tzinfo=timezone.utc)   # CEST from 29 March


def test_column_returns_aware_utc(db_session):
    db_session.add(Category(name="Test"))
    db_session.commit()
    db_session.expire_all()
    created = db_session.query(Category).filter_by(name="Test").one().created_at
    assert created.tzinfo is timezone.utc
    assert abs(utc_now() - created) < timedelta(minutes=1)


def test_column_converts_other_zones_to_utc(db_session):
    plus_two = timezone(timedelta(hours=2))
    start = datetime(2026, 7, 1, 14, 0, tzinfo=plus_two)
    db_session.add(ZReport(report_number="Z-0001", period_start=start, period_end=start))
    db_session.commit()
    db_session.expire_all()
    stored = db_session.query(ZReport).one().period_start
    assert stored == datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    assert stored.tzinfo is timezone.utc


def test_column_refuses_naive(db_session):
    naive = datetime(2026, 7, 1, 14, 0)
    db_session.add(ZReport(report_number="Z-0001", period_start=naive, period_end=naive))
    with pytest.raises(Exception, match="Naive datetime"):
        db_session.commit()
