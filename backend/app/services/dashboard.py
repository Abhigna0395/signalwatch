"""Dashboard aggregation.

One endpoint, one round trip. The brief is explicit that the frontend must not
call twenty endpoints to render the homepage, and there is a real reason beyond
tidiness: the "since your last visit" section, the attention queue and the
watchlist rows are all *views over the same analysis*. Computing that analysis
once and slicing it is both faster and internally consistent — three panels can
never disagree about NVDA's score because they are reading the same object.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Event, User, Watchlist
from app.providers.registry import get_market_data_service
from app.services.analysis import AnalysisBundle, analyze_stocks
from app.services.market_clock import greeting, in_market_status, us_market_status
from app.services.signal_engine import Category
from app.services.user_state import last_reviewed_at, record_visit, touch_viewed
from app.services.watchlists import (
    all_stocks_for_user,
    list_watchlists,
    thresholds_for_user,
)
from app.services.world import get_world_step
from app.timeutil import age_seconds, humanize_age, to_iso, utcnow

# Index proxies shown in the Market Pulse strip. In demo mode these are derived
# from the demo world so they stay internally consistent with the watchlist.
_INDEX_PROXIES = [
    ("S&P 500", ["AAPL", "MSFT", "JPM", "AMZN", "GOOGL"]),
    ("NASDAQ", ["NVDA", "MSFT", "AAPL", "META", "AMZN"]),
    ("DOW", ["JPM", "MSFT", "AAPL"]),
]


def build_dashboard(db: Session, user: User, *, watchlist_id: int | None = None) -> dict:
    stocks = all_stocks_for_user(db, user.id)
    watchlists = list_watchlists(db, user.id)

    if not stocks:
        return _empty_dashboard(db, user, watchlists)

    bundles = analyze_stocks(
        db, stocks, user_id=user.id, thresholds=thresholds_for_user(db, user.id), persist=True
    )

    changed = [b for b in bundles.values() if b.ok and b.signal.since_last_visit.is_meaningful]
    changed.sort(key=lambda b: b.signal.score, reverse=True)

    # Record the visit *after* computing, so the count is accurate; recording it
    # does not move any baseline (see services/user_state.py).
    record_visit(db, user.id, changes_seen=len(changed))
    touch_viewed(db, user.id, [b.stock.id for b in bundles.values() if b.ok])
    db.commit()

    scored = [b for b in bundles.values() if b.ok]
    scored.sort(key=lambda b: b.signal.score, reverse=True)

    attention_queue = [b.row_dict() for b in scored if b.signal.band != "STABLE"]
    stable = [b.row_dict() for b in scored if b.signal.band == "STABLE"]
    unavailable = [b.row_dict() for b in bundles.values() if not b.ok]

    reviewed = last_reviewed_at(db, user.id)

    return {
        "greeting": greeting(),
        "generated_at": to_iso(utcnow()),
        "last_visit": {
            "last_reviewed_at": to_iso(reviewed),
            "label": humanize_age(age_seconds(reviewed)) if reviewed else "never",
            "has_reviewed": reviewed is not None,
        },
        "market_status": _market_status(stocks),
        "summary": _summary(scored, changed),
        "since_last_visit": {
            "count": len(changed),
            "changes": [_change_card(b) for b in changed],
            "empty_message": "Nothing meaningful changed since your last visit.",
        },
        "attention_queue": attention_queue,
        "stable_stocks": stable,
        "unavailable": unavailable,
        "watchlists": [
            _watchlist_summary(w, bundles, selected=(watchlist_id == w.id)) for w in watchlists
        ],
        "recent_events": _recent_events(db, [b.stock.id for b in scored]),
        "data_quality": _data_quality(bundles),
        "config": {
            "thresholds": {
                "high_attention": settings.threshold_high_attention,
                "watch": settings.threshold_watch,
            },
            "weights": settings.weights.as_dict(),
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Sections
# ─────────────────────────────────────────────────────────────────────────────


def _summary(scored: list[AnalysisBundle], changed: list[AnalysisBundle]) -> dict:
    bands = {"HIGH_ATTENTION": 0, "WATCH": 0, "STABLE": 0}
    for bundle in scored:
        bands[bundle.signal.band] = bands.get(bundle.signal.band, 0) + 1
    return {
        "tracked": len(scored),
        "meaningful_changes": len(changed),
        "high_attention": bands["HIGH_ATTENTION"],
        "watch": bands["WATCH"],
        "stable": bands["STABLE"],
        "headline": _headline(changed, bands),
    }


def _headline(changed: list[AnalysisBundle], bands: dict) -> str:
    if not changed:
        return "Nothing meaningful changed since your last visit."
    count = len(changed)
    noun = "change" if count == 1 else "changes"
    top = changed[0]
    return (
        f"{count} meaningful {noun} — {top.stock.symbol} needs the most attention "
        f"({top.signal.top_reason.lower()})."
    )


def _change_card(bundle: AnalysisBundle) -> dict:
    """One card in the "Since your last visit" section."""
    signal = bundle.signal
    since = signal.since_last_visit
    card = bundle.row_dict()
    card.update(
        {
            "why_it_matters": signal.why_it_matters,
            "headline": since.headline,
            "reasons": [c.detail for c in signal.components if c.points > 1.0][:4],
            "new_signals": [
                {
                    "fingerprint": e.fingerprint,
                    "title": e.title,
                    "category": e.category.value,
                    "severity": e.severity.value,
                    "direction": e.direction,
                }
                for e in signal.events
                if e.fingerprint in set(since.new_signals)
            ],
            "resolved_signals": since.resolved_signals,
            "escalated": since.escalated,
        }
    )
    return card


def _watchlist_summary(
    watchlist: Watchlist, bundles: dict[str, AnalysisBundle], *, selected: bool
) -> dict:
    rows = []
    for item in sorted(watchlist.items, key=lambda i: i.position):
        bundle = bundles.get(item.stock.symbol)
        if bundle is None:
            continue
        row = bundle.row_dict()
        row["position"] = item.position
        row["threshold_percent"] = item.threshold_percent
        rows.append(row)

    scores = [r["score"] for r in rows]
    return {
        "id": watchlist.id,
        "name": watchlist.name,
        "position": watchlist.position,
        "selected": selected,
        "count": len(rows),
        "items": rows,
        "high_attention": len([r for r in rows if r["band"] == "HIGH_ATTENTION"]),
        "changed": len([r for r in rows if r.get("since_last_visit", {}).get("is_meaningful")]),
        "average_score": round(sum(scores) / len(scores), 1) if scores else 0.0,
    }


def _recent_events(db: Session, stock_ids: list[int], limit: int = 12) -> list[dict]:
    if not stock_ids:
        return []
    rows = db.scalars(
        select(Event)
        .where(Event.stock_id.in_(stock_ids), Event.category != Category.DATA.value)
        .order_by(Event.timestamp.desc())
        .limit(limit)
    )
    now = utcnow()
    return [
        {
            "id": row.id,
            "symbol": row.stock.symbol,
            "type": row.type,
            "category": row.category,
            "severity": row.severity,
            "direction": row.direction,
            "title": row.title,
            "timestamp": to_iso(row.timestamp),
            "label": humanize_age(age_seconds(row.timestamp, now=now)),
        }
        for row in rows
    ]


def _market_status(stocks) -> dict:
    """Market session plus index proxies."""
    service = get_market_data_service()
    us = us_market_status()
    india = in_market_status()

    indices = []
    if service.is_demo:
        # Derive index proxies from the same demo world, so the strip cannot
        # contradict the watchlist sitting directly beneath it.
        quotes = service.get_quotes([s for _, group in _INDEX_PROXIES for s in group])
        for name, members in _INDEX_PROXIES:
            changes = [
                quotes[m].quote.change_percent
                for m in members
                if m in quotes and quotes[m].quote.change_percent is not None
            ]
            if changes:
                indices.append(
                    {
                        "name": name,
                        "change_percent": round(sum(changes) / len(changes), 2),
                        "is_proxy": True,
                    }
                )

    return {
        "primary": us,
        "sessions": [us, india],
        "indices": indices,
        "is_demo": service.is_demo,
        "provider": service.primary.name,
        "replay_step": get_world_step() if service.is_demo else None,
    }


def _data_quality(bundles: dict[str, AnalysisBundle]) -> dict:
    """A single honest verdict on how much to trust this whole screen."""
    service = get_market_data_service()
    ok = [b for b in bundles.values() if b.ok]

    counts = {"FRESH": 0, "RECENT": 0, "STALE": 0, "UNAVAILABLE": 0}
    conflicts, delayed = [], []
    for bundle in ok:
        status = bundle.resolved.freshness.status.value
        counts[status] = counts.get(status, 0) + 1
        if bundle.resolved.verification == "conflict" and bundle.resolved.discrepancy:
            d = bundle.resolved.discrepancy
            conflicts.append(
                {
                    "symbol": bundle.stock.symbol,
                    "source_a": d.source_a, "value_a": d.value_a,
                    "source_b": d.source_b, "value_b": d.value_b,
                    "difference_percent": d.difference_percent,
                    "tolerance_percent": d.tolerance_percent,
                    "resolved_with": d.resolved_with,
                    "reason": d.reason,
                }
            )
        if bundle.resolved.freshness.is_delayed:
            delayed.append(
                {
                    "symbol": bundle.stock.symbol,
                    "label": bundle.resolved.freshness.label,
                    "age_seconds": bundle.resolved.freshness.age_seconds,
                }
            )

    missing = [b.stock.symbol for b in bundles.values() if not b.ok]
    if missing or counts["UNAVAILABLE"]:
        status = "DEGRADED"
    elif conflicts or counts["STALE"]:
        status = "PARTIAL"
    else:
        status = "HEALTHY"

    return {
        "status": status,
        "is_demo": service.is_demo,
        "provider": service.primary.name,
        "fallback_reason": service.fallback_reason,
        "freshness_counts": counts,
        "conflicts": conflicts,
        "delayed": delayed,
        "missing": missing,
        "sources": [
            {
                "name": h.name, "kind": h.kind, "is_primary": h.is_primary, "status": h.status,
                "success_count": h.success_count, "error_count": h.error_count,
                "last_success_at": to_iso(h.last_success_at),
                "last_error_at": to_iso(h.last_error_at),
                "last_error": h.last_error,
            }
            for h in service.source_health()
        ],
        "tolerance_percent": settings.discrepancy_tolerance_percent,
    }


def _empty_dashboard(db: Session, user: User, watchlists: list[Watchlist]) -> dict:
    """First-run state: no stocks tracked yet."""
    from app.services.watchlists import STARTER_SYMBOLS

    record_visit(db, user.id, changes_seen=0)
    db.commit()
    service = get_market_data_service()

    return {
        "greeting": greeting(),
        "generated_at": to_iso(utcnow()),
        "last_visit": {"last_reviewed_at": None, "label": "never", "has_reviewed": False},
        "market_status": _market_status([]),
        "summary": {
            "tracked": 0, "meaningful_changes": 0, "high_attention": 0, "watch": 0, "stable": 0,
            "headline": "Build your first market watchlist.",
        },
        "since_last_visit": {
            "count": 0, "changes": [],
            "empty_message": "Add a few stocks and SignalWatch will start tracking what changes.",
        },
        "attention_queue": [],
        "stable_stocks": [],
        "unavailable": [],
        "watchlists": [
            _watchlist_summary(w, {}, selected=False) for w in watchlists
        ],
        "recent_events": [],
        "data_quality": {
            "status": "HEALTHY", "is_demo": service.is_demo, "provider": service.primary.name,
            "fallback_reason": service.fallback_reason,
            "freshness_counts": {"FRESH": 0, "RECENT": 0, "STALE": 0, "UNAVAILABLE": 0},
            "conflicts": [], "delayed": [], "missing": [], "sources": [],
            "tolerance_percent": settings.discrepancy_tolerance_percent,
        },
        "onboarding": {
            "is_first_run": True,
            "title": "Build your first market watchlist.",
            "description": (
                "SignalWatch tracks what you have already seen, so when you come back it can "
                "show you only what actually changed."
            ),
            "suggested": STARTER_SYMBOLS,
        },
        "config": {
            "thresholds": {
                "high_attention": settings.threshold_high_attention,
                "watch": settings.threshold_watch,
            },
            "weights": settings.weights.as_dict(),
        },
    }


def build_changes_since_last_visit(db: Session, user: User) -> dict:
    """The standalone `/api/changes/since-last-visit` view."""
    stocks = all_stocks_for_user(db, user.id)
    if not stocks:
        return {"count": 0, "changes": [], "last_reviewed_at": None}

    bundles = analyze_stocks(
        db, stocks, user_id=user.id, thresholds=thresholds_for_user(db, user.id), persist=False
    )
    changed = [b for b in bundles.values() if b.ok and b.signal.since_last_visit.is_meaningful]
    changed.sort(key=lambda b: b.signal.score, reverse=True)
    reviewed = last_reviewed_at(db, user.id)
    return {
        "count": len(changed),
        "changes": [_change_card(b) for b in changed],
        "last_reviewed_at": to_iso(reviewed),
        "label": humanize_age(age_seconds(reviewed)) if reviewed else "never",
    }
