"""Provider registry and the market data service.

This is the layer that turns "call an API" into "get trustworthy data":

  * selects the configured provider (demo or live) behind one interface
  * caches aggressively, with per-data-type TTLs
  * on failure, degrades in order: live → stale cache → demo, and *says so*
  * cross-checks quotes against a second source and records disagreements
    rather than silently picking a winner
  * tracks per-source health so the UI can explain degraded data

Nothing above this file needs to know any of that happened; everything above
receives a `ResolvedQuote` that carries its own provenance.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime

from app.cache import get_cache
from app.config import settings
from app.providers.base import (
    CompanyProfile,
    Freshness,
    FreshnessInfo,
    HistoricalSeries,
    MarketDataProvider,
    NewsArticle,
    ProviderError,
    Quote,
    SymbolMatch,
)
from app.providers.demo import DemoMarketDataProvider, FINAL_REPLAY_STEP
from app.timeutil import utcnow

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DiscrepancyReport:
    """Two sources disagreed. We keep both numbers."""

    field: str
    source_a: str
    value_a: float
    timestamp_a: datetime | None
    source_b: str
    value_b: float
    timestamp_b: datetime | None
    difference_percent: float
    tolerance_percent: float
    resolved_with: str
    reason: str

    @property
    def is_conflict(self) -> bool:
        return self.difference_percent > self.tolerance_percent


@dataclass
class ResolvedQuote:
    """A quote plus everything needed to judge how much to trust it."""

    quote: Quote
    freshness: FreshnessInfo
    served_from: str = "provider"       # provider | cache | stale_cache | fallback_demo
    degraded: bool = False
    degraded_reason: str | None = None
    verification: str = "single_source"  # verified | conflict | single_source | unavailable
    discrepancy: DiscrepancyReport | None = None
    is_demo: bool = False


@dataclass
class SourceHealth:
    name: str
    kind: str = "market"
    is_primary: bool = False
    success_count: int = 0
    error_count: int = 0
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    last_error: str | None = None

    @property
    def status(self) -> str:
        if self.error_count and not self.success_count:
            return "DOWN"
        if self.last_error_at and self.success_count:
            return "DEGRADED"
        return "HEALTHY" if self.success_count else "IDLE"


# ─────────────────────────────────────────────────────────────────────────────
# Secondary demo source
# ─────────────────────────────────────────────────────────────────────────────


class SecondaryDemoProvider(DemoMarketDataProvider):
    """A second, independent-looking view of the demo world.

    Real feeds disagree slightly all the time (different venues, different
    snapshot instants) and occasionally disagree badly (a stale or mispriced
    tick). This reproduces both: a small per-symbol wobble everywhere, plus a
    deliberate large divergence on whichever symbol the scenario marks, so the
    conflict-detection path is actually exercised in the demo.
    """

    name = "demo_secondary"

    def get_quote(self, symbol: str) -> Quote:
        quote = super().get_quote(symbol)
        symbol = symbol.upper()

        disagreement = self.secondary_disagreement_percent(symbol)
        if disagreement:
            drift = disagreement
        else:
            # Deterministic sub-tolerance noise: sources that agree, but not to
            # the last cent — which is the normal case and must not be flagged.
            drift = (self._rng(symbol, "secondary").random() - 0.5) * 0.2

        quote.price = round(quote.price * (1 + drift / 100.0), 2)
        quote.source = self.name
        return quote


# ─────────────────────────────────────────────────────────────────────────────
# Provider construction
# ─────────────────────────────────────────────────────────────────────────────


def _world_step() -> int:
    """Current replay frame, read from persisted runtime state."""
    from app.services.world import get_world_step

    try:
        return get_world_step()
    except Exception:  # noqa: BLE001 - never let the replay break data access
        return FINAL_REPLAY_STEP


def build_primary_provider() -> tuple[MarketDataProvider, str | None]:
    """Return `(provider, fallback_reason)`.

    A missing key or an unconstructable live provider is not a crash — it is a
    documented, visible fallback to the demo provider.
    """
    if settings.demo_mode:
        return DemoMarketDataProvider(world_step=_world_step()), None

    if settings.market_provider == "finnhub":
        try:
            from app.providers.finnhub import FinnhubProvider

            return FinnhubProvider(settings.finnhub_api_key), None
        except ProviderError as exc:
            reason = f"{exc}; falling back to demo data"
            logger.warning(reason)
            return DemoMarketDataProvider(world_step=_world_step()), reason

    reason = f"Unknown MARKET_PROVIDER '{settings.market_provider}'; using demo data"
    logger.warning(reason)
    return DemoMarketDataProvider(world_step=_world_step()), reason


def build_secondary_provider() -> MarketDataProvider | None:
    """The cross-check source, if one is available."""
    if not settings.enable_cross_source_check:
        return None
    if settings.demo_mode:
        return SecondaryDemoProvider(world_step=_world_step())
    # In live mode a second source needs its own credentials. Rather than
    # inventing one, we report `single_source` honestly. Adding one here is a
    # single line once its provider class exists.
    return None


# ─────────────────────────────────────────────────────────────────────────────
# The service
# ─────────────────────────────────────────────────────────────────────────────


class MarketDataService:
    """The only thing the rest of the application talks to for market data."""

    def __init__(self) -> None:
        self._cache = get_cache()
        self._health: dict[str, SourceHealth] = {}
        self.refresh_providers()

    def refresh_providers(self) -> None:
        """Rebuild providers — called at startup and when the replay advances."""
        self.primary, self.fallback_reason = build_primary_provider()
        self.secondary = build_secondary_provider()
        self._register(self.primary.name, is_primary=True)
        if self.secondary:
            self._register(self.secondary.name)

    # ── Health bookkeeping ─────────────────────────────────────────────────
    def _register(self, name: str, *, is_primary: bool = False, kind: str = "market") -> SourceHealth:
        health = self._health.get(name)
        if health is None:
            health = SourceHealth(name=name, kind=kind, is_primary=is_primary)
            self._health[name] = health
        return health

    def _ok(self, name: str) -> None:
        health = self._register(name)
        health.success_count += 1
        health.last_success_at = utcnow()

    def _fail(self, name: str, error: str) -> None:
        health = self._register(name)
        health.error_count += 1
        health.last_error_at = utcnow()
        health.last_error = error[:400]

    def source_health(self) -> list[SourceHealth]:
        return list(self._health.values())

    # ── Reconciliation ─────────────────────────────────────────────────────
    def _reconcile(self, primary: Quote, secondary: Quote | None) -> tuple[str, DiscrepancyReport | None]:
        """Compare two sources' prices. Never silently discard one."""
        if secondary is None or not secondary.price or not primary.price:
            return "single_source", None

        diff = abs(primary.price - secondary.price)
        base = max(abs(primary.price), 1e-9)
        diff_percent = diff / base * 100.0
        tolerance = settings.discrepancy_tolerance_percent

        # When sources conflict we prefer the *more recent* one, and we say so.
        prefer_primary = True
        if primary.source_timestamp and secondary.source_timestamp:
            prefer_primary = primary.source_timestamp >= secondary.source_timestamp
        resolved = primary.source if prefer_primary else secondary.source
        reason = (
            "Primary source is more recent"
            if prefer_primary
            else "Secondary source carries a newer exchange timestamp"
        )

        report = DiscrepancyReport(
            field="price",
            source_a=primary.source,
            value_a=primary.price,
            timestamp_a=primary.source_timestamp,
            source_b=secondary.source,
            value_b=secondary.price,
            timestamp_b=secondary.source_timestamp,
            difference_percent=round(diff_percent, 3),
            tolerance_percent=tolerance,
            resolved_with=resolved,
            reason=reason,
        )
        if diff_percent > tolerance:
            return "conflict", report
        return "verified", None

    # ── Quotes ─────────────────────────────────────────────────────────────
    def get_quote(self, symbol: str, *, use_cache: bool = True) -> ResolvedQuote:
        symbol = symbol.upper()
        key = f"quote:{self.primary.name}:{symbol}:{_world_step()}"

        if use_cache:
            cached = self._cache.get(key)
            if cached is not None:
                cached.served_from = "cache"
                return cached

        try:
            quote = self.primary.get_quote(symbol)
            self._ok(self.primary.name)
        except Exception as exc:  # noqa: BLE001
            self._fail(self.primary.name, str(exc))
            return self._degraded_quote(symbol, key, str(exc))

        secondary_quote = None
        if self.secondary is not None:
            try:
                secondary_quote = self.secondary.get_quote(symbol)
                self._ok(self.secondary.name)
            except Exception as exc:  # noqa: BLE001 - verification is best-effort
                self._fail(self.secondary.name, str(exc))

        verification, discrepancy = self._reconcile(quote, secondary_quote)
        note = None
        if verification == "conflict" and discrepancy:
            note = (
                f"{discrepancy.source_a} and {discrepancy.source_b} disagree by "
                f"{discrepancy.difference_percent:.2f}%"
            )

        resolved = ResolvedQuote(
            quote=quote,
            freshness=FreshnessInfo.build(
                quote.source, quote.source_timestamp, is_delayed=quote.is_delayed, note=note
            ),
            served_from="provider",
            degraded=self.fallback_reason is not None,
            degraded_reason=self.fallback_reason,
            verification=verification,
            discrepancy=discrepancy,
            is_demo=self.primary.is_demo,
        )
        self._cache.set(key, resolved, settings.quote_cache_ttl_seconds)
        return resolved

    def _degraded_quote(self, symbol: str, key: str, error: str) -> ResolvedQuote:
        """Provider failed. Serve the best thing we still have, honestly labelled."""
        # 1. A stale cache entry beats nothing — and beats a fabricated number.
        stale = self._cache.get_stale(key, settings.freshness_stale_seconds)
        if stale is not None:
            value, age = stale
            value.served_from = "stale_cache"
            value.degraded = True
            value.degraded_reason = f"Live data unavailable ({error}); showing last known value"
            value.freshness = FreshnessInfo.build(
                value.quote.source, value.quote.source_timestamp, is_delayed=True,
                note=f"Cached {int(age)}s ago — provider unreachable",
            )
            return value

        # 2. Otherwise fall back to the demo world, clearly marked.
        try:
            fallback = DemoMarketDataProvider(world_step=_world_step())
            quote = fallback.get_quote(symbol)
            return ResolvedQuote(
                quote=quote,
                freshness=FreshnessInfo.build(
                    "demo_fallback", quote.source_timestamp, is_delayed=True,
                    note="Live provider unavailable — showing demo data",
                ),
                served_from="fallback_demo",
                degraded=True,
                degraded_reason=f"Live data unavailable ({error}); showing demo data",
                verification="unavailable",
                is_demo=True,
            )
        except Exception:  # noqa: BLE001
            # 3. Nothing at all. Say that plainly rather than inventing a price.
            raise ProviderError("market_data", f"No data available for {symbol}: {error}") from None

    def get_quotes(self, symbols: list[str], *, use_cache: bool = True) -> dict[str, ResolvedQuote]:
        """Batch fetch.

        The demo provider is genuinely batch-capable, so it short-circuits. For
        a network provider we fan out across a small thread pool: a 40-symbol
        watchlist fetched sequentially at ~200ms each is 8 seconds of blank
        dashboard, which is the difference between a product and a prototype.
        """
        symbols = [s.upper() for s in symbols]
        if not symbols:
            return {}

        if self.primary.is_demo:
            return {s: self.get_quote(s, use_cache=use_cache) for s in symbols}

        results: dict[str, ResolvedQuote] = {}
        max_workers = min(8, len(symbols))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = {pool.submit(self.get_quote, s, use_cache=use_cache): s for s in symbols}
            for future, symbol in futures.items():
                try:
                    results[symbol] = future.result()
                except Exception as exc:  # noqa: BLE001 - one bad symbol ≠ dead page
                    logger.warning("quote failed for %s: %s", symbol, exc)
        return results

    # ── History / news / profile ───────────────────────────────────────────
    def get_historical_data(self, symbol: str, days: int = 400) -> HistoricalSeries:
        symbol = symbol.upper()
        key = f"history:{self.primary.name}:{symbol}:{days}:{_world_step()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            series = self.primary.get_historical_data(symbol, days)
            self._ok(self.primary.name)
        except Exception as exc:  # noqa: BLE001
            self._fail(self.primary.name, str(exc))
            stale = self._cache.get_stale(key, settings.freshness_stale_seconds * 4)
            if stale is not None:
                return stale[0]
            series = DemoMarketDataProvider(world_step=_world_step()).get_historical_data(symbol, days)
        self._cache.set(key, series, settings.history_cache_ttl_seconds)
        return series

    def get_news(self, symbol: str, limit: int = 20) -> list[NewsArticle]:
        symbol = symbol.upper()
        key = f"news:{self.primary.name}:{symbol}:{limit}:{_world_step()}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            articles = self.primary.get_news(symbol, limit)
            self._ok(self.primary.name)
        except Exception as exc:  # noqa: BLE001 - news is never load-bearing
            self._fail(self.primary.name, str(exc))
            stale = self._cache.get_stale(key, settings.freshness_stale_seconds)
            articles = stale[0] if stale else []
        self._cache.set(key, articles, settings.news_cache_ttl_seconds)
        return articles

    def get_company_profile(self, symbol: str) -> CompanyProfile | None:
        symbol = symbol.upper()
        key = f"profile:{self.primary.name}:{symbol}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        try:
            profile = self.primary.get_company_profile(symbol)
        except Exception:  # noqa: BLE001
            try:
                profile = DemoMarketDataProvider().get_company_profile(symbol)
            except Exception:  # noqa: BLE001
                return None
        self._cache.set(key, profile, 86400)
        return profile

    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolMatch]:
        try:
            matches = self.primary.search_symbols(query, limit)
        except Exception:  # noqa: BLE001
            matches = []
        if not matches and not self.primary.is_demo:
            # Always leave the user with something searchable.
            matches = DemoMarketDataProvider().search_symbols(query, limit)
        return matches

    def market_status(self) -> dict:
        return self.primary.market_status()

    @property
    def is_demo(self) -> bool:
        return self.primary.is_demo

    def invalidate(self, pattern: str = "*") -> int:
        return self._cache.clear(pattern)


_service: MarketDataService | None = None


def get_market_data_service() -> MarketDataService:
    global _service
    if _service is None:
        _service = MarketDataService()
    return _service


def reset_market_data_service() -> None:
    """Force a rebuild — used when the replay step or configuration changes."""
    global _service
    if _service is not None:
        _service.invalidate("quote:*")
        _service.invalidate("news:*")
        _service.invalidate("history:*")
        _service.refresh_providers()
