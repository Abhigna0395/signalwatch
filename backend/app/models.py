"""SQLAlchemy models.

Indexing strategy (see README → Scalability): every column used to filter or
order a hot query carries an index, and the two heaviest tables
(`market_snapshots`, `events`) carry composite `(stock_id, timestamp DESC)`
indexes because every read of them is "latest N for this stock".
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from app.timeutil import utcnow


class Base(DeclarativeBase):
    pass


# ─────────────────────────────────────────────────────────────────────────────
# Identity
# ─────────────────────────────────────────────────────────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120), default="Demo User")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    watchlists: Mapped[list["Watchlist"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", order_by="Watchlist.position"
    )


class VisitSession(Base):
    """One row per time the user opened the dashboard.

    `reviewed_at` is set when the user presses "Mark all as reviewed" — that,
    not the page load, is what moves the since-last-visit baseline forward.
    """

    __tablename__ = "visit_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    changes_seen: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (Index("ix_visit_sessions_user_started", "user_id", "started_at"),)


# ─────────────────────────────────────────────────────────────────────────────
# Watchlists
# ─────────────────────────────────────────────────────────────────────────────
class Watchlist(Base):
    __tablename__ = "watchlists"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    position: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    user: Mapped[User] = relationship(back_populates="watchlists")
    items: Mapped[list["WatchlistItem"]] = relationship(
        back_populates="watchlist",
        cascade="all, delete-orphan",
        order_by="WatchlistItem.position",
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_watchlist_user_name"),)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    watchlist_id: Mapped[int] = mapped_column(
        ForeignKey("watchlists.id", ondelete="CASCADE"), index=True
    )
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    # Optional per-item alert: "tell me if this moves more than N%".
    threshold_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")
    stock: Mapped["Stock"] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("watchlist_id", "stock_id", name="uq_watchlist_stock"),
        Index("ix_watchlist_items_wl_pos", "watchlist_id", "position"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Instruments & market data
# ─────────────────────────────────────────────────────────────────────────────
class Stock(Base):
    __tablename__ = "stocks"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    exchange: Mapped[str] = mapped_column(String(40), default="")
    sector: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(8), default="USD")


class MarketSnapshot(Base):
    """A point-in-time quote as reported by one source.

    We keep the full history rather than overwriting: the timeline, the
    since-last-visit deltas and the discrepancy audit trail all read from it.
    """

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    price: Mapped[float] = mapped_column(Float)
    previous_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    change_percent: Mapped[float | None] = mapped_column(Float, nullable=True)
    open_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    day_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Float, nullable=True)
    week52_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    week52_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(8), default="USD")

    # Provenance — never lose track of where a number came from.
    source: Mapped[str] = mapped_column(String(48), index=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    is_delayed: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (Index("ix_snapshots_stock_time", "stock_id", "timestamp"),)


class DataSource(Base):
    """Health ledger for each provider, so the UI can explain degraded data."""

    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(48), unique=True, index=True)
    kind: Mapped[str] = mapped_column(String(24), default="market")  # market | news
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)


class DataDiscrepancy(Base):
    """Recorded whenever two sources disagree beyond tolerance.

    We store both values rather than silently picking a winner.
    """

    __tablename__ = "data_discrepancies"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(32), default="price")
    source_a: Mapped[str] = mapped_column(String(48))
    value_a: Mapped[float] = mapped_column(Float)
    timestamp_a: Mapped[datetime] = mapped_column(DateTime)
    source_b: Mapped[str] = mapped_column(String(48))
    value_b: Mapped[float] = mapped_column(Float)
    timestamp_b: Mapped[datetime] = mapped_column(DateTime)
    difference_percent: Mapped[float] = mapped_column(Float)
    resolved_with: Mapped[str] = mapped_column(String(48))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Intelligence
# ─────────────────────────────────────────────────────────────────────────────
class Event(Base):
    """A normalised, typed thing that happened to a stock."""

    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40), index=True)
    category: Mapped[str] = mapped_column(String(24), index=True)
    severity: Mapped[str] = mapped_column(String(16), default="info")
    direction: Mapped[str] = mapped_column(String(12), default="neutral")
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=0.5)
    source: Mapped[str] = mapped_column(String(48), default="signal_engine")
    # Stable identity for "is this the *same* event as last time?" comparisons.
    fingerprint: Mapped[str] = mapped_column(String(120), index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    stock: Mapped[Stock] = relationship(lazy="joined")

    __table_args__ = (Index("ix_events_stock_time", "stock_id", "timestamp"),)


class Signal(Base):
    """A persisted attention-score computation, with its full breakdown."""

    __tablename__ = "signals"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, index=True)
    band: Mapped[str] = mapped_column(String(20), default="STABLE")
    top_reason: Mapped[str] = mapped_column(String(120), default="")
    explanation: Mapped[dict] = mapped_column(JSON, default=dict)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)

    __table_args__ = (Index("ix_signals_stock_time", "stock_id", "timestamp"),)


class NewsItem(Base):
    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)
    headline: Mapped[str] = mapped_column(String(400))
    summary: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(80), default="")
    url: Mapped[str] = mapped_column(String(600), default="")
    topic: Mapped[str] = mapped_column(String(80), default="General")
    sentiment: Mapped[str] = mapped_column(String(16), default="neutral")
    sentiment_confidence: Mapped[float] = mapped_column(Float, default=0.5)
    sentiment_provider: Mapped[str] = mapped_column(String(24), default="keyword")
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    external_id: Mapped[str] = mapped_column(String(120), index=True, default="")
    ingested_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("stock_id", "external_id", name="uq_news_stock_external"),
        Index("ix_news_stock_published", "stock_id", "published_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# The heart of the product: what the user has already seen
# ─────────────────────────────────────────────────────────────────────────────
class UserStockState(Base):
    """The user's acknowledged baseline for one stock.

    Everything in "Since you last checked" is a diff between this row and the
    live world. It moves forward only on an explicit review.
    """

    __tablename__ = "user_stock_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    stock_id: Mapped[int] = mapped_column(ForeignKey("stocks.id", ondelete="CASCADE"), index=True)

    last_seen_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_volume: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_seen_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Technical regime at review time, e.g. {"above_sma50": true, "rsi_zone": "neutral"}
    last_seen_technical: Mapped[dict] = mapped_column(JSON, default=dict)
    # Fingerprints of the events that were live at review time.
    last_seen_event_fingerprints: Mapped[list] = mapped_column(JSON, default=list)
    last_seen_news_count: Mapped[int] = mapped_column(Integer, default=0)
    last_seen_news_sentiment: Mapped[str | None] = mapped_column(String(16), nullable=True)

    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_viewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_seen_signal_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "stock_id", name="uq_user_stock_state"),
        Index("ix_user_stock_state_user", "user_id", "stock_id"),
    )


class AppState(Base):
    """Tiny key/value store for singleton runtime state (e.g. the replay step)."""

    __tablename__ = "app_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
