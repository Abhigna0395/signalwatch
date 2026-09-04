"""REST API.

Routes stay thin: validate, delegate to a service, serialise. All domain rules
live in `app/services/`, which is what keeps them testable without a HTTP client
and reusable from the seed script and the background worker.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models import Stock, User
from app.providers.registry import get_market_data_service
from app.schemas import (
    ItemsReorder,
    MarkReviewedRequest,
    MessageOut,
    ReplayStepRequest,
    StockAdd,
    SymbolMatchOut,
    ThresholdUpdate,
    WatchlistCreate,
    WatchlistOut,
    WatchlistReorder,
    WatchlistUpdate,
)
from app.services import watchlists as wl
from app.services.analysis import analyze_one, analyze_stocks, build_timeline, price_history
from app.services.dashboard import build_changes_since_last_visit, build_dashboard
from app.services.news import cluster_news
from app.services.user_state import mark_reviewed, reset_baseline
from app.services.watchlists import WatchlistError
from app.services.world import get_world_step, replay_script, set_world_step
from app.timeutil import to_iso, utcnow

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def _handle(exc: WatchlistError):
    raise HTTPException(status_code=exc.status_code, detail=exc.message)


def _get_stock(db: Session, symbol: str) -> Stock:
    stock = db.scalars(select(Stock).where(Stock.symbol == symbol.strip().upper())).first()
    if stock is None:
        raise HTTPException(status_code=404, detail=f"'{symbol.upper()}' is not being tracked")
    return stock


# ─────────────────────────────────────────────────────────────────────────────
# Health
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/health", tags=["system"], summary="Liveness and provider status")
def health(db: Session = Depends(get_db)) -> dict:
    service = get_market_data_service()
    try:
        db.execute(select(1))
        db_ok = True
    except Exception as exc:  # noqa: BLE001
        logger.error("database health check failed: %s", exc)
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "time": to_iso(utcnow()),
        "database": "ok" if db_ok else "unreachable",
        "demo_mode": settings.demo_mode,
        "provider": service.primary.name,
        "provider_is_demo": service.is_demo,
        "fallback_reason": service.fallback_reason,
        "replay_step": get_world_step() if service.is_demo else None,
        "sources": [
            {"name": h.name, "status": h.status, "success": h.success_count,
             "errors": h.error_count}
            for h in service.source_health()
        ],
    }


@router.get("/config", tags=["system"], summary="Scoring configuration")
def get_config() -> dict:
    """Exposes the weights so the UI can render the score breakdown honestly."""
    return {
        "weights": settings.weights.as_dict(),
        "weights_total": settings.weights.total,
        "thresholds": {
            "high_attention": settings.threshold_high_attention,
            "watch": settings.threshold_watch,
        },
        "detection": {
            "price_move_notable_percent": settings.price_move_notable_percent,
            "volume_spike_ratio": settings.volume_spike_ratio,
            "volatility_spike_ratio": settings.volatility_spike_ratio,
            "since_visit_notable_percent": settings.since_visit_notable_percent,
            "news_spike_count": settings.news_spike_count,
        },
        "freshness_seconds": {
            "fresh": settings.freshness_fresh_seconds,
            "recent": settings.freshness_recent_seconds,
            "stale": settings.freshness_stale_seconds,
        },
        "discrepancy_tolerance_percent": settings.discrepancy_tolerance_percent,
        "demo_mode": settings.demo_mode,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/dashboard", tags=["dashboard"], summary="Everything the homepage needs")
def dashboard(
    watchlist_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    return build_dashboard(db, user, watchlist_id=watchlist_id)


@router.get("/changes/since-last-visit", tags=["dashboard"], summary="Meaningful changes only")
def changes_since_last_visit(
    db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    return build_changes_since_last_visit(db, user)


@router.post("/changes/mark-reviewed", tags=["dashboard"], summary="Acknowledge current state")
def mark_changes_reviewed(
    payload: MarkReviewedRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Move the user's baseline forward to the world as it stands right now."""
    stocks = wl.all_stocks_for_user(db, user.id)
    if not stocks:
        return {"reviewed": 0, "message": "Nothing to review"}

    bundles = analyze_stocks(
        db, stocks, user_id=user.id, thresholds=wl.thresholds_for_user(db, user.id), persist=False
    )
    symbols = payload.symbols if payload else None
    count = mark_reviewed(db, user.id, bundles, symbols=symbols)
    return {
        "reviewed": count,
        "reviewed_at": to_iso(utcnow()),
        "message": f"Marked {count} stock{'s' if count != 1 else ''} as reviewed",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Watchlists
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/watchlists", response_model=list[WatchlistOut], tags=["watchlists"])
def list_watchlists(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return wl.list_watchlists(db, user.id)


@router.post("/watchlists", response_model=WatchlistOut, status_code=201, tags=["watchlists"])
def create_watchlist(
    payload: WatchlistCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return wl.create_watchlist(db, user.id, payload.name)
    except WatchlistError as exc:
        _handle(exc)


@router.get("/watchlists/{watchlist_id}", response_model=WatchlistOut, tags=["watchlists"])
def get_watchlist(
    watchlist_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        return wl.get_watchlist(db, user.id, watchlist_id)
    except WatchlistError as exc:
        _handle(exc)


@router.patch("/watchlists/{watchlist_id}", response_model=WatchlistOut, tags=["watchlists"])
def rename_watchlist(
    watchlist_id: int,
    payload: WatchlistUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return wl.rename_watchlist(db, user.id, watchlist_id, payload.name)
    except WatchlistError as exc:
        _handle(exc)


@router.delete("/watchlists/{watchlist_id}", response_model=MessageOut, tags=["watchlists"])
def delete_watchlist(
    watchlist_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    try:
        wl.delete_watchlist(db, user.id, watchlist_id)
    except WatchlistError as exc:
        _handle(exc)
    return MessageOut(message="Watchlist deleted")


@router.post("/watchlists/reorder", response_model=list[WatchlistOut], tags=["watchlists"])
def reorder_watchlists(
    payload: WatchlistReorder,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return wl.reorder_watchlists(db, user.id, payload.ordered_ids)
    except WatchlistError as exc:
        _handle(exc)


@router.post(
    "/watchlists/{watchlist_id}/stocks", response_model=WatchlistOut, status_code=201,
    tags=["watchlists"],
)
def add_stock(
    watchlist_id: int,
    payload: StockAdd,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        wl.add_stock(
            db, user.id, watchlist_id, payload.symbol,
            threshold_percent=payload.threshold_percent,
        )
        return wl.get_watchlist(db, user.id, watchlist_id)
    except WatchlistError as exc:
        _handle(exc)


@router.delete(
    "/watchlists/{watchlist_id}/stocks/{symbol}", response_model=WatchlistOut, tags=["watchlists"]
)
def remove_stock(
    watchlist_id: int,
    symbol: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        wl.remove_stock(db, user.id, watchlist_id, symbol)
        return wl.get_watchlist(db, user.id, watchlist_id)
    except WatchlistError as exc:
        _handle(exc)


@router.post(
    "/watchlists/{watchlist_id}/reorder", response_model=WatchlistOut, tags=["watchlists"]
)
def reorder_items(
    watchlist_id: int,
    payload: ItemsReorder,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        return wl.reorder_items(db, user.id, watchlist_id, payload.ordered_symbols)
    except WatchlistError as exc:
        _handle(exc)


@router.patch(
    "/watchlists/{watchlist_id}/stocks/{symbol}", response_model=WatchlistOut, tags=["watchlists"]
)
def set_threshold(
    watchlist_id: int,
    symbol: str,
    payload: ThresholdUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        wl.set_threshold(db, user.id, watchlist_id, symbol, payload.threshold_percent)
        return wl.get_watchlist(db, user.id, watchlist_id)
    except WatchlistError as exc:
        _handle(exc)


@router.post("/watchlists/starter", response_model=WatchlistOut, status_code=201, tags=["watchlists"])
def create_starter(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """One-click onboarding: a populated watchlist with meaningful scenarios."""
    return wl.create_starter_watchlist(db, user)


# ─────────────────────────────────────────────────────────────────────────────
# Stocks
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/stocks/search", response_model=list[SymbolMatchOut], tags=["stocks"])
def search_stocks(q: str = Query(min_length=1, max_length=64), limit: int = Query(10, ge=1, le=25)):
    return wl.search_stocks(q, limit)


@router.get("/stocks/{symbol}", tags=["stocks"], summary="Full detail view for one stock")
def get_stock(
    symbol: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    stock = _get_stock(db, symbol)
    thresholds = wl.thresholds_for_user(db, user.id)
    bundle = analyze_one(db, stock, user_id=user.id, threshold=thresholds.get(stock.id))
    if not bundle.ok:
        raise HTTPException(
            status_code=503,
            detail=bundle.error or "Market data temporarily unavailable for this stock",
        )
    detail = bundle.detail_dict()
    detail["timeline"] = build_timeline(db, stock.id)
    return detail


@router.get("/stocks/{symbol}/history", tags=["stocks"])
def get_history(
    symbol: str,
    range: str = Query("3M", pattern="^(1D|1W|1M|3M|1Y|1d|1w|1m|3m|1y)$"),
    db: Session = Depends(get_db),
) -> dict:
    _get_stock(db, symbol)
    return price_history(db, symbol.upper(), range)


@router.get("/stocks/{symbol}/signals", tags=["stocks"])
def get_signals(
    symbol: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)
) -> dict:
    stock = _get_stock(db, symbol)
    thresholds = wl.thresholds_for_user(db, user.id)
    bundle = analyze_one(db, stock, user_id=user.id, threshold=thresholds.get(stock.id), persist=False)
    if not bundle.ok:
        raise HTTPException(status_code=503, detail=bundle.error or "Unavailable")
    return {
        "symbol": stock.symbol,
        "score": bundle.signal.score,
        "band": bundle.signal.band,
        "top_reason": bundle.signal.top_reason,
        "why_it_matters": bundle.signal.why_it_matters,
        "confidence": bundle.signal.confidence,
        "explanation": bundle.signal.explanation(),
        "events": [e.to_dict() for e in bundle.signal.events],
        "since_last_visit": bundle.signal.since_last_visit.to_dict(),
    }


@router.get("/stocks/{symbol}/news", tags=["stocks"])
def get_news(symbol: str, db: Session = Depends(get_db)) -> dict:
    from app.services.news import _recent_news_rows, ingest_news

    stock = _get_stock(db, symbol)
    service = get_market_data_service()
    try:
        rows = ingest_news(db, stock, service.get_news(stock.symbol, limit=20))
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("news fetch failed for %s: %s", symbol, exc)
        rows = _recent_news_rows(db, stock.id)

    clusters = cluster_news(rows)
    return {
        "symbol": stock.symbol,
        "clusters": [c.to_dict() for c in clusters],
        "total": sum(c.count for c in clusters),
        "empty_message": "No recent catalysts detected.",
    }


@router.get("/stocks/{symbol}/timeline", tags=["stocks"])
def get_timeline(symbol: str, db: Session = Depends(get_db)) -> dict:
    stock = _get_stock(db, symbol)
    return {"symbol": stock.symbol, "timeline": build_timeline(db, stock.id)}


# ─────────────────────────────────────────────────────────────────────────────
# Demo / replay
# ─────────────────────────────────────────────────────────────────────────────


@router.get("/demo/replay", tags=["demo"], summary="The replay script and current frame")
def get_replay() -> dict:
    service = get_market_data_service()
    return {
        "available": service.is_demo,
        "current_step": get_world_step(),
        "steps": replay_script(),
    }


@router.post("/demo/replay/step", tags=["demo"], summary="Advance or set the replay frame")
def advance_replay(
    payload: ReplayStepRequest | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> dict:
    """Move the demo world forward.

    This genuinely changes the data the provider returns, so the signal engine
    re-detects from scratch on the next request — the score movement is real,
    not a scripted animation.
    """
    service = get_market_data_service()
    if not service.is_demo:
        raise HTTPException(status_code=409, detail="Replay is only available in demo mode")

    requested = payload.step if payload and payload.step is not None else get_world_step() + 1
    step = set_world_step(requested)
    script = replay_script()
    return {
        "current_step": step,
        "frame": script[step] if step < len(script) else None,
        "steps": script,
        "is_final": step >= len(script) - 1,
    }


@router.post("/demo/replay/reset", tags=["demo"], summary="Return to the 'before' world")
def reset_replay(db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> dict:
    """Rewind to frame 0 and re-baseline the user against it.

    That combination is what makes the replay a true demonstration of the core
    loop: the user has now "already seen" the quiet world, so every subsequent
    step produces genuine, unseen change.
    """
    service = get_market_data_service()
    if not service.is_demo:
        raise HTTPException(status_code=409, detail="Replay is only available in demo mode")

    set_world_step(0)
    stocks = wl.all_stocks_for_user(db, user.id)
    if stocks:
        reset_baseline(db, user.id, [s.id for s in stocks])
        bundles = analyze_stocks(db, stocks, user_id=user.id, persist=False)
        mark_reviewed(db, user.id, bundles)

    return {
        "current_step": 0,
        "steps": replay_script(),
        "message": "Replay reset — the quiet market is now your reviewed baseline",
    }
