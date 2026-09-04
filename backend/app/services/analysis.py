"""Analysis orchestration.

Turns "a list of stocks" into "scored, explained, persisted intelligence".

This is the only place that knows how to assemble a `SignalInput` from the
provider layer, the indicator layer and the user's stored baseline. Keeping that
assembly here means the signal engine stays pure and the API routes stay thin.

Performance shape (see README → Scalability):
  * quotes are fetched in one batch call, never per-symbol in a loop
  * history and its derived indicators are cached, not recomputed per render
  * snapshots/events are persisted on a throttle, so opening the dashboard
    fifty times does not write fifty identical rows
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache import get_cache
from app.config import settings
from app.models import Event, MarketSnapshot, NewsItem, Signal, Stock, UserStockState
from app.providers.registry import ResolvedQuote, get_market_data_service
from app.services.indicators import TechnicalState, compute_technical_state
from app.services.news import NewsCluster, cluster_news, ingest_news, to_scored_news
from app.services.signal_engine import (
    Baseline,
    Category,
    DataQuality,
    SignalInput,
    SignalResult,
    get_signal_engine,
)
from app.timeutil import age_seconds, to_iso, utcnow

logger = logging.getLogger(__name__)

# Don't write a new snapshot/event row more often than this per stock.
_PERSIST_THROTTLE_SECONDS = 45


@dataclass
class AnalysisBundle:
    """Everything known about one stock at one moment."""

    stock: Stock
    resolved: ResolvedQuote | None
    technical: TechnicalState
    signal: SignalResult | None
    news_rows: list[NewsItem] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.signal is not None and self.resolved is not None

    def news_clusters(self) -> list[NewsCluster]:
        return cluster_news(self.news_rows)

    # ── Serialization ──────────────────────────────────────────────────────
    def quote_dict(self) -> dict:
        if not self.resolved:
            return {}
        q = self.resolved.quote
        return {
            "price": q.price,
            "previous_close": q.previous_close,
            "change_absolute": _r(q.change_absolute, 2),
            "change_percent": _r(q.change_percent, 2),
            "open": q.open,
            "day_high": q.day_high,
            "day_low": q.day_low,
            "volume": q.volume,
            "avg_volume": q.avg_volume,
            "volume_ratio": _r(self.technical.volume_ratio20, 2),
            "market_cap": q.market_cap,
            "week52_high": q.week52_high,
            "week52_low": q.week52_low,
            "currency": q.currency,
        }

    def freshness_dict(self) -> dict:
        if not self.resolved:
            return {
                "status": "UNAVAILABLE", "label": "unavailable", "source": "none",
                "age_seconds": None, "is_delayed": True, "note": self.error,
                "served_from": "none", "verification": "unavailable", "is_demo": False,
            }
        f = self.resolved.freshness
        return {
            "status": f.status.value,
            "label": f.label,
            "source": f.source,
            "source_timestamp": to_iso(f.source_timestamp),
            "age_seconds": _r(f.age_seconds, 0),
            "is_delayed": f.is_delayed,
            "note": f.note,
            "served_from": self.resolved.served_from,
            "degraded": self.resolved.degraded,
            "degraded_reason": self.resolved.degraded_reason,
            "verification": self.resolved.verification,
            "is_demo": self.resolved.is_demo,
            "discrepancy": _discrepancy_dict(self.resolved),
        }

    def row_dict(self) -> dict:
        """The compact shape used by the attention queue and watchlist rows."""
        s = self.signal
        return {
            "symbol": self.stock.symbol,
            "name": self.stock.name,
            "exchange": self.stock.exchange,
            "sector": self.stock.sector,
            "currency": self.stock.currency,
            "quote": self.quote_dict(),
            "freshness": self.freshness_dict(),
            "score": round(s.score, 1) if s else 0.0,
            "band": s.band if s else "STABLE",
            "top_reason": s.top_reason if s else "Data unavailable",
            "confidence": round(s.confidence, 2) if s else 0.0,
            "since_last_visit": s.since_last_visit.to_dict() if s else {},
            "event_count": len([e for e in s.events if e.category is not Category.DATA]) if s else 0,
            "categories": sorted({e.category.value for e in s.events}) if s else [],
            "error": self.error,
        }

    def detail_dict(self) -> dict:
        base = self.row_dict()
        base.update(
            {
                "why_it_matters": self.signal.why_it_matters if self.signal else "",
                "explanation": self.signal.explanation() if self.signal else {},
                "events": [e.to_dict() for e in self.signal.events] if self.signal else [],
                "news": [c.to_dict() for c in self.news_clusters()],
                "technical": {
                    "sma20": _r(self.technical.sma20, 2),
                    "sma50": _r(self.technical.sma50, 2),
                    "rsi14": _r(self.technical.rsi14, 1),
                    "rsi_zone": self.technical.rsi_zone,
                    "volatility_20d": _r(self.technical.volatility20, 2),
                    "volatility_baseline": _r(self.technical.volatility_baseline, 2),
                    "volatility_ratio": _r(self.technical.volatility_ratio, 2),
                    "resistance60": _r(self.technical.resistance60, 2),
                    "support60": _r(self.technical.support60, 2),
                    "move_zscore": _r(self.technical.move_zscore, 2),
                },
            }
        )
        return base


def _r(value, digits: int):
    return None if value is None else round(value, digits)


def _discrepancy_dict(resolved: ResolvedQuote) -> dict | None:
    d = resolved.discrepancy
    if d is None:
        return None
    return {
        "field": d.field,
        "source_a": d.source_a, "value_a": d.value_a, "timestamp_a": to_iso(d.timestamp_a),
        "source_b": d.source_b, "value_b": d.value_b, "timestamp_b": to_iso(d.timestamp_b),
        "difference_percent": d.difference_percent,
        "tolerance_percent": d.tolerance_percent,
        "resolved_with": d.resolved_with,
        "reason": d.reason,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Technical state (cached)
# ─────────────────────────────────────────────────────────────────────────────


def _technical_for(symbol: str, resolved: ResolvedQuote | None) -> TechnicalState:
    """Indicators for one symbol.

    The expensive half — pulling 400 bars and computing the moving averages,
    RSI and volatility baseline — depends only on the *history*, which changes
    once a day. So that half is cached on the history, and only the cheap
    today-dependent parts are recomputed per call.
    """
    if resolved is None:
        return TechnicalState()

    service = get_market_data_service()
    quote = resolved.quote
    try:
        series = service.get_historical_data(symbol, 400)
    except Exception as exc:  # noqa: BLE001
        logger.warning("history unavailable for %s: %s", symbol, exc)
        return TechnicalState()

    closes, volumes = series.closes, series.volumes
    if not closes:
        return TechnicalState()

    # Intraday highs/lows are passed through deliberately: the 52-week range must
    # be measured against prior *highs*, not prior closes. Note also that we feed
    # only the historical series — the provider's own 52-week figures include
    # today's print, which would let a stock trivially "break" its own high.
    return compute_technical_state(
        closes,
        volumes,
        current_price=quote.price,
        current_volume=quote.volume,
        change_percent=quote.change_percent,
        highs=[c.high for c in series.candles],
        lows=[c.low for c in series.candles],
    )


# ─────────────────────────────────────────────────────────────────────────────
# Baseline
# ─────────────────────────────────────────────────────────────────────────────


def load_baselines(db: Session, user_id: int, stock_ids: list[int]) -> dict[int, UserStockState]:
    if not stock_ids:
        return {}
    rows = db.scalars(
        select(UserStockState).where(
            UserStockState.user_id == user_id, UserStockState.stock_id.in_(stock_ids)
        )
    )
    return {row.stock_id: row for row in rows}


def _to_baseline(row: UserStockState | None) -> Baseline:
    if row is None:
        return Baseline()
    return Baseline(
        last_seen_price=row.last_seen_price,
        last_seen_volume=row.last_seen_volume,
        last_seen_score=row.last_seen_score,
        last_seen_band=row.last_seen_band,
        last_seen_technical=row.last_seen_technical or {},
        last_seen_event_fingerprints=list(row.last_seen_event_fingerprints or []),
        last_seen_news_count=row.last_seen_news_count or 0,
        last_seen_news_sentiment=row.last_seen_news_sentiment,
        last_reviewed_at=row.last_reviewed_at,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Orchestration
# ─────────────────────────────────────────────────────────────────────────────


def analyze_stocks(
    db: Session,
    stocks: list[Stock],
    *,
    user_id: int,
    thresholds: dict[int, float] | None = None,
    persist: bool = True,
    with_news: bool = True,
) -> dict[str, AnalysisBundle]:
    """Analyse a set of stocks in one pass."""
    if not stocks:
        return {}

    service = get_market_data_service()
    engine = get_signal_engine()
    thresholds = thresholds or {}

    symbols = [s.symbol for s in stocks]
    quotes = service.get_quotes(symbols)          # one batch call
    baselines = load_baselines(db, user_id, [s.id for s in stocks])

    bundles: dict[str, AnalysisBundle] = {}
    now = utcnow()

    for stock in stocks:
        resolved = quotes.get(stock.symbol)
        if resolved is None:
            bundles[stock.symbol] = AnalysisBundle(
                stock=stock, resolved=None, technical=TechnicalState(), signal=None,
                error="Market data temporarily unavailable",
            )
            continue

        technical = _technical_for(stock.symbol, resolved)

        news_rows: list[NewsItem] = []
        if with_news:
            try:
                articles = service.get_news(stock.symbol, limit=20)
                news_rows = ingest_news(db, stock, articles)
            except Exception as exc:  # noqa: BLE001 - news must never break a render
                logger.warning("news unavailable for %s: %s", stock.symbol, exc)

        quote = resolved.quote
        signal_input = SignalInput(
            symbol=stock.symbol,
            name=stock.name,
            currency=quote.currency or stock.currency,
            price=quote.price,
            previous_close=quote.previous_close,
            change_percent=quote.change_percent,
            open_price=quote.open,
            volume=quote.volume,
            avg_volume=quote.avg_volume,
            technical=technical,
            news=to_scored_news(news_rows),
            baseline=_to_baseline(baselines.get(stock.id)),
            data_quality=DataQuality(
                freshness=resolved.freshness.status.value,
                age_seconds=resolved.freshness.age_seconds,
                source=resolved.freshness.source,
                is_delayed=resolved.freshness.is_delayed,
                verification=resolved.verification,
                has_conflict=resolved.verification == "conflict",
                conflict_note=resolved.freshness.note,
                is_demo=resolved.is_demo,
            ),
            user_threshold_percent=thresholds.get(stock.id),
            now=now,
        )

        signal = engine.evaluate(signal_input)
        bundles[stock.symbol] = AnalysisBundle(
            stock=stock, resolved=resolved, technical=technical,
            signal=signal, news_rows=news_rows,
        )

    if persist:
        try:
            _persist(db, bundles)
            db.commit()
        except Exception as exc:  # noqa: BLE001 - persistence is not worth a 500
            db.rollback()
            logger.warning("failed to persist analysis: %s", exc)

    return bundles


def analyze_one(
    db: Session, stock: Stock, *, user_id: int, threshold: float | None = None, persist: bool = True
) -> AnalysisBundle:
    bundles = analyze_stocks(
        db, [stock], user_id=user_id,
        thresholds={stock.id: threshold} if threshold else {}, persist=persist,
    )
    return bundles.get(
        stock.symbol,
        AnalysisBundle(stock=stock, resolved=None, technical=TechnicalState(), signal=None,
                       error="Market data temporarily unavailable"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Persistence
# ─────────────────────────────────────────────────────────────────────────────


def _persist(db: Session, bundles: dict[str, AnalysisBundle]) -> None:
    """Write snapshots, events and signals — throttled, and deduplicated.

    The timeline is built from these rows, so they must be written; but a
    dashboard that is refreshed every few seconds must not write a row every
    time. Events additionally deduplicate on `fingerprint`: a volume spike that
    persists for three hours is one timeline entry, not two hundred.
    """
    cache = get_cache()
    now = utcnow()

    for bundle in bundles.values():
        if not bundle.ok:
            continue
        stock, resolved, signal = bundle.stock, bundle.resolved, bundle.signal
        throttle_key = f"persist:{stock.id}"
        if cache.get(throttle_key) is not None:
            continue
        cache.set(throttle_key, True, _PERSIST_THROTTLE_SECONDS)

        quote = resolved.quote
        db.add(
            MarketSnapshot(
                stock_id=stock.id,
                price=quote.price,
                previous_close=quote.previous_close,
                change_percent=quote.change_percent,
                open_price=quote.open,
                day_high=quote.day_high,
                day_low=quote.day_low,
                volume=quote.volume,
                avg_volume=quote.avg_volume,
                market_cap=quote.market_cap,
                week52_high=quote.week52_high,
                week52_low=quote.week52_low,
                currency=quote.currency,
                source=quote.source,
                source_timestamp=quote.source_timestamp or now,
                timestamp=now,
                is_delayed=resolved.freshness.is_delayed,
            )
        )

        db.add(
            Signal(
                stock_id=stock.id,
                score=signal.score,
                band=signal.band,
                top_reason=signal.top_reason[:120],
                explanation=signal.explanation(),
                timestamp=now,
            )
        )

        _persist_events(db, stock, signal, now)
        _persist_discrepancy(db, stock, resolved, now)


def _persist_events(db: Session, stock: Stock, signal: SignalResult, now) -> None:
    """Insert only events whose fingerprint isn't already live for this stock."""
    recent_cutoff = now - _timedelta_hours(12)
    live = {
        row.fingerprint
        for row in db.scalars(
            select(Event).where(Event.stock_id == stock.id, Event.timestamp >= recent_cutoff)
        )
    }
    for event in signal.events:
        if event.fingerprint in live:
            continue
        db.add(
            Event(
                stock_id=stock.id,
                type=event.type.value,
                category=event.category.value,
                severity=event.severity.value,
                direction=event.direction,
                title=event.title[:200],
                description=event.description,
                metrics=event.metrics,
                confidence=event.confidence,
                fingerprint=event.fingerprint[:120],
                timestamp=event.timestamp or now,
            )
        )


def _persist_discrepancy(db: Session, stock: Stock, resolved: ResolvedQuote, now) -> None:
    from app.models import DataDiscrepancy

    d = resolved.discrepancy
    if d is None or not d.is_conflict:
        return
    db.add(
        DataDiscrepancy(
            stock_id=stock.id,
            field=d.field,
            source_a=d.source_a, value_a=d.value_a, timestamp_a=d.timestamp_a or now,
            source_b=d.source_b, value_b=d.value_b, timestamp_b=d.timestamp_b or now,
            difference_percent=d.difference_percent,
            resolved_with=d.resolved_with,
            detected_at=now,
        )
    )


def _timedelta_hours(hours: float):
    from datetime import timedelta

    return timedelta(hours=hours)


# ─────────────────────────────────────────────────────────────────────────────
# Timeline
# ─────────────────────────────────────────────────────────────────────────────


def build_timeline(db: Session, stock_id: int, *, limit: int = 40) -> list[dict]:
    """Chronological event feed for the stock detail page, grouped by day."""
    rows = list(
        db.scalars(
            select(Event)
            .where(Event.stock_id == stock_id)
            .order_by(Event.timestamp.desc())
            .limit(limit)
        )
    )
    now = utcnow()
    out: list[dict] = []
    for row in rows:
        age = age_seconds(row.timestamp, now=now) or 0
        days = int(age // 86400)
        if days == 0:
            bucket = "TODAY"
        elif days == 1:
            bucket = "YESTERDAY"
        elif days < 7:
            bucket = f"{days} DAYS AGO"
        else:
            bucket = row.timestamp.strftime("%d %b %Y").upper()
        out.append(
            {
                "id": row.id,
                "bucket": bucket,
                "type": row.type,
                "category": row.category,
                "severity": row.severity,
                "direction": row.direction,
                "title": row.title,
                "description": row.description,
                "metrics": row.metrics,
                "confidence": round(row.confidence, 2),
                "timestamp": to_iso(row.timestamp),
                "clock": row.timestamp.strftime("%H:%M"),
            }
        )
    return out


def price_history(db: Session, symbol: str, range_key: str = "3M") -> dict:
    """Chart series with moving-average overlays, for one of the range presets."""
    days_for = {"1D": 2, "1W": 7, "1M": 31, "3M": 92, "1Y": 365}
    bars_for = {"1D": 2, "1W": 5, "1M": 22, "3M": 65, "1Y": 252}
    wanted = bars_for.get(range_key.upper(), 65)

    service = get_market_data_service()
    # Always pull enough history to compute a real 50-day average at the left
    # edge of the window, then trim — otherwise the overlay starts 50 bars in.
    series = service.get_historical_data(symbol, max(wanted + 60, 120))
    candles = series.candles
    if not candles:
        return {"symbol": symbol, "range": range_key, "points": [], "source": series.source}

    closes = [c.close for c in candles]
    points: list[dict] = []
    start = max(0, len(candles) - wanted)
    for i in range(start, len(candles)):
        window20 = closes[max(0, i - 19): i + 1]
        window50 = closes[max(0, i - 49): i + 1]
        points.append(
            {
                "date": candles[i].day.isoformat(),
                "close": round(candles[i].close, 2),
                "open": round(candles[i].open, 2),
                "high": round(candles[i].high, 2),
                "low": round(candles[i].low, 2),
                "volume": candles[i].volume,
                "sma20": round(sum(window20) / len(window20), 2) if len(window20) == 20 else None,
                "sma50": round(sum(window50) / len(window50), 2) if len(window50) == 50 else None,
            }
        )
    return {
        "symbol": symbol,
        "range": range_key.upper(),
        "points": points,
        "source": series.source,
        "days": days_for.get(range_key.upper(), 92),
    }
