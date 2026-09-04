"""Visit tracking and the review baseline.

The single most important design decision in this product lives here:

    **Opening the dashboard does not reset "since your last visit".
    Pressing "Mark all as reviewed" does.**

If merely loading the page moved the baseline forward, the deltas would vanish
the instant they were rendered and the feature would be useless — the user would
see "since your last visit: nothing" on every subsequent refresh, having never
had a chance to read it. So we track two timestamps with different meanings:

  * `last_viewed_at`   — when the user last *looked*. Display only.
  * `last_reviewed_at` — when the user last *acknowledged*. This is the baseline
                         every delta is measured against.

That separation is what makes the core loop work: visit → market changes →
return → the change is still there waiting to be seen.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import UserStockState, VisitSession
from app.services.analysis import AnalysisBundle
from app.timeutil import utcnow


# ─────────────────────────────────────────────────────────────────────────────
# Visits
# ─────────────────────────────────────────────────────────────────────────────


def last_visit(db: Session, user_id: int) -> VisitSession | None:
    """The most recent *completed* visit — i.e. not the one happening now."""
    return db.scalars(
        select(VisitSession)
        .where(VisitSession.user_id == user_id)
        .order_by(VisitSession.started_at.desc())
        .limit(1)
    ).first()


def last_reviewed_at(db: Session, user_id: int) -> datetime | None:
    """When the user last acknowledged the state of the world.

    Read from `UserStockState`, not `VisitSession`: the per-stock baseline is
    what the deltas are actually measured against, and it is written by every
    path that establishes a baseline — including the seed script and the replay
    reset, neither of which goes through a browser visit. Keying this off visit
    rows would report "never" for a freshly seeded database that plainly does
    have a baseline.
    """
    return db.scalar(
        select(func.max(UserStockState.last_reviewed_at)).where(
            UserStockState.user_id == user_id
        )
    )


def record_visit(db: Session, user_id: int, *, changes_seen: int = 0) -> VisitSession:
    """Log a dashboard load.

    Repeated loads inside a short window collapse into the same session, so an
    impatient refresh does not fill the activity feed with noise.
    """
    recent = db.scalars(
        select(VisitSession)
        .where(VisitSession.user_id == user_id)
        .order_by(VisitSession.started_at.desc())
        .limit(1)
    ).first()

    now = utcnow()
    if recent and recent.reviewed_at is None and (now - recent.started_at).total_seconds() < 900:
        recent.changes_seen = max(recent.changes_seen, changes_seen)
        db.flush()
        return recent

    visit = VisitSession(user_id=user_id, started_at=now, changes_seen=changes_seen)
    db.add(visit)
    db.flush()
    return visit


def touch_viewed(db: Session, user_id: int, stock_ids: list[int]) -> None:
    """Record that the user has *seen* these stocks, without moving the baseline."""
    if not stock_ids:
        return
    now = utcnow()
    existing = {
        row.stock_id: row
        for row in db.scalars(
            select(UserStockState).where(
                UserStockState.user_id == user_id, UserStockState.stock_id.in_(stock_ids)
            )
        )
    }
    for stock_id in stock_ids:
        row = existing.get(stock_id)
        if row is None:
            db.add(UserStockState(user_id=user_id, stock_id=stock_id, last_viewed_at=now))
        else:
            row.last_viewed_at = now
    db.flush()


# ─────────────────────────────────────────────────────────────────────────────
# Review
# ─────────────────────────────────────────────────────────────────────────────


def mark_reviewed(
    db: Session,
    user_id: int,
    bundles: dict[str, AnalysisBundle],
    *,
    symbols: list[str] | None = None,
) -> int:
    """Snapshot the current world as the user's new acknowledged baseline.

    Everything the "since last visit" diff compares against is written here, in
    one place: price, volume, score, band, technical regime, live event
    fingerprints and news state. Capturing the *fingerprints* (rather than just
    the score) is what later lets us distinguish a genuinely new signal from one
    the user has already seen and chosen to ignore.
    """
    wanted = {s.upper() for s in symbols} if symbols else None
    now = utcnow()

    targets = [
        b for symbol, b in bundles.items()
        if b.ok and (wanted is None or symbol.upper() in wanted)
    ]
    if not targets:
        return 0

    stock_ids = [b.stock.id for b in targets]
    existing = {
        row.stock_id: row
        for row in db.scalars(
            select(UserStockState).where(
                UserStockState.user_id == user_id, UserStockState.stock_id.in_(stock_ids)
            )
        )
    }

    for bundle in targets:
        signal = bundle.signal
        quote = bundle.resolved.quote
        row = existing.get(bundle.stock.id)
        if row is None:
            row = UserStockState(user_id=user_id, stock_id=bundle.stock.id)
            db.add(row)

        row.last_seen_price = quote.price
        row.last_seen_volume = quote.volume
        row.last_seen_score = signal.score
        row.last_seen_band = signal.band
        row.last_seen_technical = bundle.technical.regime(quote.price)
        row.last_seen_event_fingerprints = signal.fingerprints
        row.last_seen_news_count = len(
            [n for n in bundle.news_rows if _recent(n.published_at, now)]
        )
        row.last_seen_news_sentiment = _net_news_tone(bundle)
        row.last_reviewed_at = now
        row.last_viewed_at = now
        row.last_seen_signal_at = signal.computed_at or now

    # Close out the open visit so the next one is a genuinely new session.
    visit = db.scalars(
        select(VisitSession)
        .where(VisitSession.user_id == user_id, VisitSession.reviewed_at.is_(None))
        .order_by(VisitSession.started_at.desc())
        .limit(1)
    ).first()
    if visit is not None:
        visit.reviewed_at = now

    db.commit()
    return len(targets)


def _recent(published_at: datetime | None, now: datetime, hours: int = 48) -> bool:
    if published_at is None:
        return False
    return (now - published_at).total_seconds() <= hours * 3600


def _net_news_tone(bundle: AnalysisBundle) -> str | None:
    now = utcnow()
    recent = [n for n in bundle.news_rows if _recent(n.published_at, now)]
    if not recent:
        return None
    polarity = sum(
        {"positive": 1, "negative": -1}.get(n.sentiment, 0) * n.sentiment_confidence
        for n in recent
    ) / len(recent)
    if polarity > 0.25:
        return "positive"
    if polarity < -0.25:
        return "negative"
    return "mixed"


def reset_baseline(db: Session, user_id: int, stock_ids: list[int] | None = None) -> int:
    """Clear acknowledged state, so everything reads as new again.

    Used by the replay demo to return to the "before" world.
    """
    query = select(UserStockState).where(UserStockState.user_id == user_id)
    if stock_ids:
        query = query.where(UserStockState.stock_id.in_(stock_ids))
    rows = list(db.scalars(query))
    for row in rows:
        row.last_seen_price = None
        row.last_seen_volume = None
        row.last_seen_score = None
        row.last_seen_band = None
        row.last_seen_technical = {}
        row.last_seen_event_fingerprints = []
        row.last_seen_news_count = 0
        row.last_seen_news_sentiment = None
        row.last_reviewed_at = None
    db.commit()
    return len(rows)
