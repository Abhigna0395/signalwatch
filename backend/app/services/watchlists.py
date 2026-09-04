"""Watchlist CRUD and stock resolution."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Stock, User, Watchlist, WatchlistItem
from app.providers.registry import get_market_data_service

STARTER_SYMBOLS = ["NVDA", "AAPL", "MSFT", "TSLA", "AMZN"]


class WatchlistError(Exception):
    """Domain error; the API layer maps this to a 4xx with a readable message."""

    def __init__(self, message: str, status_code: int = 400):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


# ─────────────────────────────────────────────────────────────────────────────
# Stocks
# ─────────────────────────────────────────────────────────────────────────────


def resolve_stock(db: Session, symbol: str) -> Stock:
    """Find a stock, creating it from the provider's profile if it's new.

    Symbols are the user's vocabulary, but rows are the database's. This keeps
    the two in sync without requiring a pre-populated instrument master.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise WatchlistError("A symbol is required")

    stock = db.scalars(select(Stock).where(Stock.symbol == symbol)).first()
    if stock is not None:
        return stock

    profile = get_market_data_service().get_company_profile(symbol)
    if profile is None:
        raise WatchlistError(f"'{symbol}' was not found", status_code=404)

    stock = Stock(
        symbol=symbol,
        name=profile.name or symbol,
        exchange=profile.exchange or "",
        sector=profile.sector or "",
        currency=profile.currency or "USD",
    )
    db.add(stock)
    db.flush()
    return stock


def search_stocks(query: str, limit: int = 10) -> list[dict]:
    matches = get_market_data_service().search_symbols(query, limit)
    return [
        {"symbol": m.symbol, "name": m.name, "exchange": m.exchange, "currency": m.currency}
        for m in matches
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Watchlists
# ─────────────────────────────────────────────────────────────────────────────


def list_watchlists(db: Session, user_id: int) -> list[Watchlist]:
    return list(
        db.scalars(
            select(Watchlist)
            .where(Watchlist.user_id == user_id)
            .order_by(Watchlist.position, Watchlist.id)
        )
    )


def get_watchlist(db: Session, user_id: int, watchlist_id: int) -> Watchlist:
    watchlist = db.scalars(
        select(Watchlist).where(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
    ).first()
    if watchlist is None:
        raise WatchlistError("Watchlist not found", status_code=404)
    return watchlist


def create_watchlist(db: Session, user_id: int, name: str) -> Watchlist:
    name = (name or "").strip()
    if not name:
        raise WatchlistError("A watchlist name is required")
    if len(name) > 120:
        raise WatchlistError("That name is too long (120 characters maximum)")

    clash = db.scalars(
        select(Watchlist).where(
            Watchlist.user_id == user_id, func.lower(Watchlist.name) == name.lower()
        )
    ).first()
    if clash is not None:
        raise WatchlistError(f"You already have a watchlist called '{name}'", status_code=409)

    next_position = (
        db.scalar(select(func.max(Watchlist.position)).where(Watchlist.user_id == user_id)) or 0
    ) + 1
    watchlist = Watchlist(user_id=user_id, name=name, position=next_position)
    db.add(watchlist)
    db.commit()
    return watchlist


def rename_watchlist(db: Session, user_id: int, watchlist_id: int, name: str) -> Watchlist:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    name = (name or "").strip()
    if not name:
        raise WatchlistError("A watchlist name is required")

    clash = db.scalars(
        select(Watchlist).where(
            Watchlist.user_id == user_id,
            func.lower(Watchlist.name) == name.lower(),
            Watchlist.id != watchlist_id,
        )
    ).first()
    if clash is not None:
        raise WatchlistError(f"You already have a watchlist called '{name}'", status_code=409)

    watchlist.name = name
    db.commit()
    return watchlist


def delete_watchlist(db: Session, user_id: int, watchlist_id: int) -> None:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    remaining = db.scalar(
        select(func.count(Watchlist.id)).where(Watchlist.user_id == user_id)
    )
    if remaining is not None and remaining <= 1:
        raise WatchlistError("You need at least one watchlist", status_code=409)
    db.delete(watchlist)
    db.commit()


def reorder_watchlists(db: Session, user_id: int, ordered_ids: list[int]) -> list[Watchlist]:
    owned = {w.id: w for w in list_watchlists(db, user_id)}
    unknown = [i for i in ordered_ids if i not in owned]
    if unknown:
        raise WatchlistError(f"Unknown watchlist id(s): {unknown}", status_code=404)
    for position, watchlist_id in enumerate(ordered_ids):
        owned[watchlist_id].position = position
    db.commit()
    return list_watchlists(db, user_id)


# ─────────────────────────────────────────────────────────────────────────────
# Items
# ─────────────────────────────────────────────────────────────────────────────


def add_stock(
    db: Session, user_id: int, watchlist_id: int, symbol: str,
    *, threshold_percent: float | None = None,
) -> WatchlistItem:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    stock = resolve_stock(db, symbol)

    existing = db.scalars(
        select(WatchlistItem).where(
            WatchlistItem.watchlist_id == watchlist.id, WatchlistItem.stock_id == stock.id
        )
    ).first()
    if existing is not None:
        raise WatchlistError(f"{stock.symbol} is already in '{watchlist.name}'", status_code=409)

    next_position = (
        db.scalar(
            select(func.max(WatchlistItem.position)).where(
                WatchlistItem.watchlist_id == watchlist.id
            )
        )
        or 0
    ) + 1
    item = WatchlistItem(
        watchlist_id=watchlist.id, stock_id=stock.id,
        position=next_position, threshold_percent=threshold_percent,
    )
    db.add(item)
    db.commit()
    return item


def remove_stock(db: Session, user_id: int, watchlist_id: int, symbol: str) -> None:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    symbol = symbol.strip().upper()
    item = db.scalars(
        select(WatchlistItem)
        .join(Stock, Stock.id == WatchlistItem.stock_id)
        .where(WatchlistItem.watchlist_id == watchlist.id, Stock.symbol == symbol)
    ).first()
    if item is None:
        raise WatchlistError(f"{symbol} is not in '{watchlist.name}'", status_code=404)
    db.delete(item)
    db.commit()


def reorder_items(db: Session, user_id: int, watchlist_id: int, ordered_symbols: list[str]) -> Watchlist:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    by_symbol = {item.stock.symbol: item for item in watchlist.items}
    unknown = [s.upper() for s in ordered_symbols if s.upper() not in by_symbol]
    if unknown:
        raise WatchlistError(f"Not in this watchlist: {', '.join(unknown)}", status_code=404)

    for position, symbol in enumerate(ordered_symbols):
        by_symbol[symbol.upper()].position = position
    # Anything the client didn't mention keeps a stable position at the end.
    for offset, item in enumerate(
        sorted((i for s, i in by_symbol.items() if s not in {x.upper() for x in ordered_symbols}),
               key=lambda i: i.position)
    ):
        item.position = len(ordered_symbols) + offset
    db.commit()
    db.refresh(watchlist)
    return watchlist


def set_threshold(
    db: Session, user_id: int, watchlist_id: int, symbol: str, threshold_percent: float | None
) -> WatchlistItem:
    watchlist = get_watchlist(db, user_id, watchlist_id)
    symbol = symbol.strip().upper()
    item = db.scalars(
        select(WatchlistItem)
        .join(Stock, Stock.id == WatchlistItem.stock_id)
        .where(WatchlistItem.watchlist_id == watchlist.id, Stock.symbol == symbol)
    ).first()
    if item is None:
        raise WatchlistError(f"{symbol} is not in '{watchlist.name}'", status_code=404)
    if threshold_percent is not None and not (0 < abs(threshold_percent) <= 100):
        raise WatchlistError("Threshold must be between 0 and 100 percent")
    item.threshold_percent = threshold_percent
    db.commit()
    return item


def create_starter_watchlist(db: Session, user: User) -> Watchlist:
    """First-run convenience: one click to a populated, meaningful watchlist."""
    existing = db.scalars(
        select(Watchlist).where(
            Watchlist.user_id == user.id, func.lower(Watchlist.name) == "my watchlist"
        )
    ).first()
    watchlist = existing or Watchlist(user_id=user.id, name="My Watchlist", position=0)
    if existing is None:
        db.add(watchlist)
        db.flush()

    have = {item.stock.symbol for item in watchlist.items}
    position = len(have)
    for symbol in STARTER_SYMBOLS:
        if symbol in have:
            continue
        try:
            stock = resolve_stock(db, symbol)
        except WatchlistError:
            continue
        db.add(WatchlistItem(watchlist_id=watchlist.id, stock_id=stock.id, position=position))
        position += 1

    db.commit()
    db.refresh(watchlist)
    return watchlist


def all_stocks_for_user(db: Session, user_id: int) -> list[Stock]:
    """Every distinct stock across all of the user's watchlists.

    The dashboard analyses this set once, then slices it per watchlist — rather
    than analysing the same symbol once per list it appears in.
    """
    return list(
        db.scalars(
            select(Stock)
            .join(WatchlistItem, WatchlistItem.stock_id == Stock.id)
            .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
            .where(Watchlist.user_id == user_id)
            .distinct()
        )
    )


def thresholds_for_user(db: Session, user_id: int) -> dict[int, float]:
    rows = db.execute(
        select(WatchlistItem.stock_id, WatchlistItem.threshold_percent)
        .join(Watchlist, Watchlist.id == WatchlistItem.watchlist_id)
        .where(Watchlist.user_id == user_id, WatchlistItem.threshold_percent.is_not(None))
    ).all()
    # If a stock sits in two lists with different thresholds, the tighter one
    # wins — the user asked to be told at the more sensitive level somewhere.
    out: dict[int, float] = {}
    for stock_id, threshold in rows:
        if threshold is None:
            continue
        current = out.get(stock_id)
        if current is None or abs(threshold) < abs(current):
            out[stock_id] = threshold
    return out
