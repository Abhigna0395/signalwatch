"""Market data provider contract.

Everything above this layer (signal engine, dashboard, API) talks only in the
dataclasses defined here. Swapping Finnhub for Alpha Vantage, Polygon or an
internal feed means writing one new subclass — nothing else changes.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from app.config import settings
from app.timeutil import age_seconds, humanize_age


class Freshness(str, Enum):
    FRESH = "FRESH"
    RECENT = "RECENT"
    STALE = "STALE"
    UNAVAILABLE = "UNAVAILABLE"


def classify_freshness(source_timestamp: datetime | None, *, now: datetime | None = None) -> Freshness:
    """Map the age of a data point onto a freshness band."""
    age = age_seconds(source_timestamp, now=now)
    if age is None:
        return Freshness.UNAVAILABLE
    if age <= settings.freshness_fresh_seconds:
        return Freshness.FRESH
    if age <= settings.freshness_recent_seconds:
        return Freshness.RECENT
    if age <= settings.freshness_stale_seconds:
        return Freshness.STALE
    return Freshness.UNAVAILABLE


@dataclass
class FreshnessInfo:
    status: Freshness
    source: str
    source_timestamp: datetime | None
    age_seconds: float | None
    label: str
    is_delayed: bool = False
    note: str | None = None

    @classmethod
    def build(
        cls,
        source: str,
        source_timestamp: datetime | None,
        *,
        is_delayed: bool = False,
        note: str | None = None,
        now: datetime | None = None,
    ) -> "FreshnessInfo":
        status = classify_freshness(source_timestamp, now=now)
        age = age_seconds(source_timestamp, now=now)
        return cls(
            status=status,
            source=source,
            source_timestamp=source_timestamp,
            age_seconds=age,
            label=humanize_age(age),
            is_delayed=is_delayed or status in (Freshness.STALE, Freshness.UNAVAILABLE),
            note=note,
        )


@dataclass
class Quote:
    symbol: str
    price: float
    previous_close: float | None = None
    open: float | None = None
    day_high: float | None = None
    day_low: float | None = None
    volume: float | None = None
    avg_volume: float | None = None
    market_cap: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    currency: str = "USD"
    source: str = "unknown"
    source_timestamp: datetime | None = None
    is_delayed: bool = False

    @property
    def change_absolute(self) -> float | None:
        if self.previous_close in (None, 0):
            return None
        return self.price - self.previous_close

    @property
    def change_percent(self) -> float | None:
        if not self.previous_close:
            return None
        return (self.price - self.previous_close) / self.previous_close * 100.0

    @property
    def volume_ratio(self) -> float | None:
        if not self.avg_volume or self.volume is None:
            return None
        return self.volume / self.avg_volume


@dataclass
class Candle:
    day: date
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class HistoricalSeries:
    symbol: str
    candles: list[Candle] = field(default_factory=list)
    source: str = "unknown"
    source_timestamp: datetime | None = None

    @property
    def closes(self) -> list[float]:
        return [c.close for c in self.candles]

    @property
    def volumes(self) -> list[float]:
        return [c.volume for c in self.candles]


@dataclass
class NewsArticle:
    symbol: str
    external_id: str
    headline: str
    summary: str = ""
    source: str = ""
    url: str = ""
    published_at: datetime | None = None


@dataclass
class CompanyProfile:
    symbol: str
    name: str
    exchange: str = ""
    sector: str = ""
    currency: str = "USD"
    market_cap: float | None = None


@dataclass
class SymbolMatch:
    symbol: str
    name: str
    exchange: str = ""
    currency: str = "USD"


class ProviderError(RuntimeError):
    """Raised when a provider cannot satisfy a request."""

    def __init__(self, provider: str, message: str):
        self.provider = provider
        super().__init__(f"[{provider}] {message}")


class MarketDataProvider(abc.ABC):
    """The single seam between SignalWatch and the outside world."""

    name: str = "abstract"
    is_demo: bool = False

    @abc.abstractmethod
    def get_quote(self, symbol: str) -> Quote: ...

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        """Batch fetch. Subclasses with a native batch endpoint should override.

        The default is a resilient loop: one bad symbol must never take down a
        whole dashboard render.
        """
        out: dict[str, Quote] = {}
        for symbol in symbols:
            try:
                out[symbol] = self.get_quote(symbol)
            except Exception:  # noqa: BLE001 - deliberately per-symbol tolerant
                continue
        return out

    @abc.abstractmethod
    def get_historical_data(self, symbol: str, days: int = 400) -> HistoricalSeries: ...

    @abc.abstractmethod
    def get_news(self, symbol: str, limit: int = 20) -> list[NewsArticle]: ...

    @abc.abstractmethod
    def get_company_profile(self, symbol: str) -> CompanyProfile: ...

    @abc.abstractmethod
    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolMatch]: ...

    def market_status(self) -> dict:
        """Default US-equities calendar. Providers with a real calendar override."""
        from app.services.market_clock import us_market_status

        return us_market_status()
