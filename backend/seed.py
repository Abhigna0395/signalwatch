"""Seed the database so the application is useful the moment it starts.

    python seed.py            # create the demo world
    python seed.py --reset    # drop everything first

The important and slightly subtle part is the last step. We deliberately set the
demo user's review baseline to the **quiet** world (replay step 0) and then move
the live world forward to step 4. That means the very first dashboard load
already shows a real "since your last visit" story — NVDA genuinely went from an
attention score in the low 30s to the low 80s while the user was away — without
anyone having to press replay first.

The deltas are computed by the same engine that would compute them a week from
now. Nothing here is hard-coded narrative.
"""

from __future__ import annotations

import argparse
import sys
from datetime import timedelta

# The Windows console defaults to cp1252, which cannot encode the box-drawing
# and arrow characters below. Reconfiguring is friendlier than degrading the
# output for everyone else.
if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - platform glue
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from sqlalchemy import select  # noqa: E402

from app.database import SessionLocal, engine, init_db
from app.models import (
    Base,
    Event,
    MarketSnapshot,
    Signal,
    Stock,
    User,
    VisitSession,
    Watchlist,
    WatchlistItem,
)
from app.providers.demo import FINAL_REPLAY_STEP, UNIVERSE
from app.providers.registry import get_market_data_service, reset_market_data_service
from app.services.analysis import analyze_stocks
from app.services.user_state import mark_reviewed
from app.services.watchlists import resolve_stock
from app.services.world import reset_cache, set_world_step
from app.timeutil import utcnow

DEMO_EMAIL = "demo@signalwatch.app"

WATCHLISTS: list[tuple[str, list[str]]] = [
    ("My Watchlist", ["NVDA", "TSLA", "MSFT", "AAPL", "AMZN"]),
    ("AI & Semis", ["NVDA", "AMD", "MSFT", "GOOGL"]),
    ("Indian Equities", ["RELIANCE", "TCS", "INFY", "HDFCBANK"]),
    ("Watch Closely", ["META", "NFLX", "JPM"]),
]

# A per-item alert, so the USER_THRESHOLD signal has something to fire on.
THRESHOLDS = {("My Watchlist", "TSLA"): 2.5}


def reset_database() -> None:
    print("  dropping all tables …")
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def seed(reset: bool = False) -> int:
    if reset:
        reset_database()
    else:
        init_db()

    reset_cache()
    db = SessionLocal()
    try:
        # ── User ────────────────────────────────────────────────────────────
        user = db.scalars(select(User).where(User.email == DEMO_EMAIL)).first()
        if user is None:
            user = User(email=DEMO_EMAIL, display_name="Demo Analyst")
            db.add(user)
            db.commit()
            db.refresh(user)
        print(f"  user: {user.email}")

        # ── Instruments ─────────────────────────────────────────────────────
        for symbol in UNIVERSE:
            resolve_stock(db, symbol)
        db.commit()
        print(f"  stocks: {len(UNIVERSE)} instruments")

        # ── Watchlists ──────────────────────────────────────────────────────
        for position, (name, symbols) in enumerate(WATCHLISTS):
            watchlist = db.scalars(
                select(Watchlist).where(Watchlist.user_id == user.id, Watchlist.name == name)
            ).first()
            if watchlist is None:
                watchlist = Watchlist(user_id=user.id, name=name, position=position)
                db.add(watchlist)
                db.flush()

            existing = {item.stock.symbol for item in watchlist.items}
            for item_position, symbol in enumerate(symbols):
                if symbol in existing:
                    continue
                stock = resolve_stock(db, symbol)
                db.add(
                    WatchlistItem(
                        watchlist_id=watchlist.id,
                        stock_id=stock.id,
                        position=item_position,
                        threshold_percent=THRESHOLDS.get((name, symbol)),
                    )
                )
            db.commit()
            print(f"  watchlist: {name} ({len(symbols)} stocks)")

        stocks = list(db.scalars(select(Stock)))

        # ── Step 1: establish the "before" baseline ─────────────────────────
        # Rewind the world to the quiet frame and analyse it.
        print("\n  building the 'before' world (replay step 0) …")
        set_world_step(0)
        reset_market_data_service()
        before = analyze_stocks(db, stocks, user_id=user.id, persist=True)

        # Record it as reviewed: the user has "already seen" this quiet market.
        reviewed = mark_reviewed(db, user.id, before)
        print(f"    marked {reviewed} stocks as reviewed at the quiet baseline")
        for symbol in ("NVDA", "TSLA", "AAPL"):
            bundle = before.get(symbol)
            if bundle and bundle.ok:
                print(
                    f"      {symbol:<9} score {bundle.signal.score:>5.1f}  "
                    f"{bundle.signal.band:<15} {bundle.signal.top_reason}"
                )

        # Backdate the review so the UI says "2 hours ago", not "just now".
        _backdate_review(db, user.id, hours=2)

        # ── Step 2: move the world forward ──────────────────────────────────
        print("\n  advancing the world to the live frame (replay step "
              f"{FINAL_REPLAY_STEP}) …")
        set_world_step(FINAL_REPLAY_STEP)
        reset_market_data_service()
        after = analyze_stocks(db, stocks, user_id=user.id, persist=True)

        print("\n  what the user will see on first load:")
        changed = [b for b in after.values() if b.ok and b.signal.since_last_visit.is_meaningful]
        changed.sort(key=lambda b: b.signal.score, reverse=True)
        for bundle in changed:
            since = bundle.signal.since_last_visit
            delta = f"{since.score_delta:+.0f}" if since.score_delta is not None else "  new"
            print(
                f"      {bundle.stock.symbol:<9} score {bundle.signal.score:>5.1f} "
                f"({delta:>5})  {bundle.signal.band:<15} {bundle.signal.top_reason}"
            )
        print(f"\n    → {len(changed)} meaningful changes since the last visit")

        counts = {
            "market_snapshots": db.scalar(select(MarketSnapshot.id).limit(1)) is not None,
            "events": len(list(db.scalars(select(Event)))),
            "signals": len(list(db.scalars(select(Signal)))),
        }
        print(f"\n  persisted: {counts['events']} events, {counts['signals']} signals")
        return 0
    finally:
        db.close()


def _backdate_review(db, user_id: int, *, hours: int) -> None:
    """Age the review timestamps so 'last checked' reads naturally."""
    from app.models import UserStockState

    when = utcnow() - timedelta(hours=hours)
    for row in db.scalars(select(UserStockState).where(UserStockState.user_id == user_id)):
        row.last_reviewed_at = when
        row.last_viewed_at = when
    for visit in db.scalars(select(VisitSession).where(VisitSession.user_id == user_id)):
        visit.started_at = when - timedelta(minutes=5)
        if visit.reviewed_at:
            visit.reviewed_at = when
    db.commit()


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the SignalWatch database")
    parser.add_argument("--reset", action="store_true", help="drop all tables first")
    args = parser.parse_args()

    print("\nSignalWatch — seeding\n" + "─" * 60)
    code = seed(reset=args.reset)
    service = get_market_data_service()
    print("─" * 60)
    print(f"provider: {service.primary.name}  (demo={service.is_demo})")
    print("done. start the API with:  uvicorn app.main:app --reload --port 8000\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
