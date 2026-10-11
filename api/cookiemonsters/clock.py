"""Time is only ever kept at ISO-week granularity (plus the UTC day for
rate-limit bookkeeping, which is deleted when the day ends)."""

from __future__ import annotations

import datetime as dt


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_week(d: dt.date) -> str:
    y, w, _ = d.isocalendar()
    return f"{y}-W{w:02d}"


def day(d: dt.date) -> str:
    return d.isoformat()


def window_weeks(today: dt.date, n: int) -> list[str]:
    """The current ISO week and the n-1 before it, oldest first."""
    return [iso_week(today - dt.timedelta(weeks=i)) for i in range(n - 1, -1, -1)]


def parse_week(s: str) -> str:
    """Validate 'YYYY-Www'; return it normalised."""
    y, w = s.split("-W")
    dt.date.fromisocalendar(int(y), int(w), 1)
    return f"{int(y):04d}-W{int(w):02d}"
