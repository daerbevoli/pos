"""
Time helpers. Every timestamp the POS stores is a timezone-aware UTC
datetime (see UTCDateTime in app/models/models.py); it's turned into the
PC's local time only for display, printing and calendar-day logic — a
"day" in a report or on an invoice is a day in the shop, not in UTC.

Local time is the operating system's timezone (with its DST rules), the same
clock the cashier sees in the taskbar.
"""
from datetime import date, datetime, time, timedelta, timezone


def utc_now() -> datetime:
    """Now, as an aware UTC datetime — the value to store."""
    return datetime.now(timezone.utc)


def to_local(dt: datetime) -> datetime:
    """An aware datetime in the PC's local timezone. Refuses a naive one:
    it can't be told whether it's UTC or local already."""
    if dt.tzinfo is None:
        raise ValueError(f"Naive datetime {dt!r}: expected a timezone-aware one")
    return dt.astimezone()


def format_local(dt: datetime | None, fmt: str, empty: str = "") -> str:
    """`dt` in local time, formatted with strftime `fmt`; `empty` for None."""
    return empty if dt is None else to_local(dt).strftime(fmt)


def local_day_start(day: date) -> datetime:
    """Local midnight at the start of `day`, as an aware UTC datetime."""
    # A naive datetime's astimezone() reads it as local time.
    return datetime.combine(day, time.min).astimezone(timezone.utc)


def local_days_range(start: date, end: date) -> tuple[datetime, datetime]:
    """[from, to) in UTC covering the local calendar days start..end, both
    inclusive — for filtering stored timestamps by the shop's dates."""
    return local_day_start(start), local_day_start(end + timedelta(days=1))
