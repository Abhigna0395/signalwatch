"""Time helpers.

Rule for the whole codebase: **datetimes are naive UTC in the database**, and
only become timezone-aware at the serialization boundary. SQLite silently drops
tzinfo, so mixing aware and naive values is the single easiest way to get a
`TypeError: can't subtract offset-naive and offset-aware datetimes` in front of
a judge. One convention, applied everywhere, avoids it.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def utcnow() -> datetime:
    """Current time as a naive UTC datetime."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_naive_utc(dt: datetime | None) -> datetime | None:
    """Normalise any datetime to naive UTC."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def to_iso(dt: datetime | None) -> str | None:
    """Serialize a naive-UTC datetime as an explicit UTC ISO-8601 string."""
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc).isoformat()


def age_seconds(dt: datetime | None, *, now: datetime | None = None) -> float | None:
    """Seconds elapsed since `dt`. Never negative (clock skew is clamped to 0)."""
    if dt is None:
        return None
    ref = now or utcnow()
    return max(0.0, (ref - as_naive_utc(dt)).total_seconds())


def humanize_age(seconds: float | None) -> str:
    """'28 sec ago' / '18 min ago' / '3 hr ago' / '2 days ago'."""
    if seconds is None:
        return "unknown"
    if seconds < 60:
        return f"{int(seconds)} sec ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
    days = int(seconds // 86400)
    return "1 day ago" if days == 1 else f"{days} days ago"


def days_ago(n: int) -> datetime:
    return utcnow() - timedelta(days=n)
