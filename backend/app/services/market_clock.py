"""Market session calendar (US equities + NSE), with no external dependency."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone

# US holidays that matter for a 2025–2026 demo window. Kept short on purpose:
# a full exchange calendar is a library, not a hackathon feature.
US_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25",
    "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    "2025-01-01", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
    "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
}

_ET = timezone(timedelta(hours=-4))  # US Eastern, DST-approximate
_IST = timezone(timedelta(hours=5, minutes=30))


def _session(now_utc: datetime, tz, open_t: time, close_t: time, label: str, exchange: str) -> dict:
    local = now_utc.replace(tzinfo=timezone.utc).astimezone(tz)
    is_weekend = local.weekday() >= 5
    is_holiday = local.strftime("%Y-%m-%d") in US_HOLIDAYS and exchange == "US"
    within = open_t <= local.time() <= close_t
    is_open = within and not is_weekend and not is_holiday

    if is_open:
        state, detail = "OPEN", f"Closes at {close_t.strftime('%I:%M %p').lstrip('0')} {label}"
    elif is_weekend:
        state, detail = "CLOSED", "Weekend"
    elif is_holiday:
        state, detail = "CLOSED", "Market holiday"
    elif local.time() < open_t:
        state, detail = "PRE_MARKET", f"Opens at {open_t.strftime('%I:%M %p').lstrip('0')} {label}"
    else:
        state, detail = "AFTER_HOURS", "Regular session closed"

    return {
        "exchange": exchange,
        "state": state,
        "is_open": is_open,
        "detail": detail,
        "local_time": local.strftime("%I:%M %p").lstrip("0") + f" {label}",
    }


def us_market_status(now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    return _session(now_utc, _ET, time(9, 30), time(16, 0), "ET", "US")


def in_market_status(now_utc: datetime | None = None) -> dict:
    now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    return _session(now_utc, _IST, time(9, 15), time(15, 30), "IST", "IN")


def greeting(now_utc: datetime | None = None) -> str:
    now_utc = now_utc or datetime.now(timezone.utc).replace(tzinfo=None)
    hour = now_utc.replace(tzinfo=timezone.utc).astimezone(_ET).hour
    if hour < 12:
        return "Good morning"
    if hour < 18:
        return "Good afternoon"
    return "Good evening"
