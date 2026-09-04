"""Live market data via Finnhub.

This is the "real" provider. It implements exactly the same interface as the
demo provider, so nothing above this file knows or cares which one is active.

Resilience is the point of most of the code here: retries with backoff, hard
timeouts, and typed `ProviderError`s so the registry can fall back cleanly
rather than surfacing a 500 to the dashboard.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone

import httpx

from app.config import settings
from app.providers.base import (
    Candle,
    CompanyProfile,
    HistoricalSeries,
    MarketDataProvider,
    NewsArticle,
    ProviderError,
    Quote,
    SymbolMatch,
)
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

_BASE_URL = "https://finnhub.io/api/v1"


class FinnhubProvider(MarketDataProvider):
    name = "finnhub"
    is_demo = False

    def __init__(self, api_key: str, timeout: float | None = None, max_retries: int | None = None):
        if not api_key:
            raise ProviderError(self.name, "FINNHUB_API_KEY is not configured")
        self._api_key = api_key
        self._timeout = timeout or settings.provider_timeout_seconds
        self._max_retries = max_retries if max_retries is not None else settings.provider_max_retries
        self._client = httpx.Client(timeout=self._timeout, base_url=_BASE_URL)

    # ── HTTP plumbing ──────────────────────────────────────────────────────
    def _get(self, path: str, params: dict) -> dict | list:
        params = {**params, "token": self._api_key}
        last_error: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                response = self._client.get(path, params=params)
                if response.status_code == 429:
                    # Rate limited: back off rather than hammering the free tier.
                    raise ProviderError(self.name, "rate limited (HTTP 429)")
                response.raise_for_status()
                return response.json()
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self._max_retries:
                    time.sleep(0.4 * (2**attempt))  # 0.4s, 0.8s, 1.6s …
                    continue
        raise ProviderError(self.name, f"GET {path} failed: {last_error}")

    # ── Interface ──────────────────────────────────────────────────────────
    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        data = self._get("/quote", {"symbol": symbol})
        if not isinstance(data, dict) or data.get("c") in (None, 0):
            raise ProviderError(self.name, f"no quote data for {symbol}")

        # Finnhub returns the quote's own exchange timestamp in `t` (epoch
        # seconds). We use it rather than "now" so the freshness layer reports
        # the age of the *data*, not the age of our request.
        epoch = data.get("t")
        source_ts = (
            datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
            if epoch
            else utcnow()
        )

        profile = self._safe_profile(symbol)
        metrics = self._safe_metrics(symbol)

        return Quote(
            symbol=symbol,
            price=float(data["c"]),
            previous_close=_opt_float(data.get("pc")),
            open=_opt_float(data.get("o")),
            day_high=_opt_float(data.get("h")),
            day_low=_opt_float(data.get("l")),
            volume=metrics.get("volume"),
            avg_volume=metrics.get("avg_volume"),
            market_cap=profile.market_cap if profile else None,
            week52_high=metrics.get("week52_high"),
            week52_low=metrics.get("week52_low"),
            currency=profile.currency if profile else "USD",
            source=self.name,
            source_timestamp=source_ts,
            is_delayed=False,
        )

    def get_historical_data(self, symbol: str, days: int = 400) -> HistoricalSeries:
        symbol = symbol.upper()
        now = utcnow()
        # Ask for calendar days generously so we get `days` *trading* bars.
        start = now - timedelta(days=int(days * 1.5) + 10)
        data = self._get(
            "/stock/candle",
            {
                "symbol": symbol,
                "resolution": "D",
                "from": int(start.replace(tzinfo=timezone.utc).timestamp()),
                "to": int(now.replace(tzinfo=timezone.utc).timestamp()),
            },
        )
        if not isinstance(data, dict) or data.get("s") != "ok":
            raise ProviderError(self.name, f"no candle data for {symbol}")

        candles = [
            Candle(
                day=datetime.fromtimestamp(t, tz=timezone.utc).date(),
                open=float(o),
                high=float(h),
                low=float(low),
                close=float(c),
                volume=float(v),
            )
            for t, o, h, low, c, v in zip(
                data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
            )
        ]
        candles.sort(key=lambda c: c.day)
        return HistoricalSeries(
            symbol=symbol, candles=candles[-days:], source=self.name, source_timestamp=utcnow()
        )

    def get_news(self, symbol: str, limit: int = 20) -> list[NewsArticle]:
        symbol = symbol.upper()
        today = utcnow().date()
        data = self._get(
            "/company-news",
            {
                "symbol": symbol,
                "from": (today - timedelta(days=7)).isoformat(),
                "to": today.isoformat(),
            },
        )
        if not isinstance(data, list):
            return []

        articles: list[NewsArticle] = []
        for item in data[:limit]:
            epoch = item.get("datetime")
            articles.append(
                NewsArticle(
                    symbol=symbol,
                    external_id=str(item.get("id") or item.get("url") or item.get("headline", ""))[:120],
                    headline=str(item.get("headline", "")).strip(),
                    summary=str(item.get("summary", "")).strip(),
                    source=str(item.get("source", "")).strip(),
                    url=str(item.get("url", "")),
                    published_at=(
                        datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None)
                        if epoch
                        else utcnow()
                    ),
                )
            )
        return [a for a in articles if a.headline]

    def get_company_profile(self, symbol: str) -> CompanyProfile:
        profile = self._safe_profile(symbol.upper())
        if profile is None:
            raise ProviderError(self.name, f"no profile for {symbol}")
        return profile

    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolMatch]:
        data = self._get("/search", {"q": query})
        results = data.get("result", []) if isinstance(data, dict) else []
        matches: list[SymbolMatch] = []
        for item in results:
            # Filter out the noise: options, warrants and foreign line items
            # that a user searching "NVIDIA" never means.
            if item.get("type") not in (None, "", "Common Stock", "ADR", "EQS"):
                continue
            symbol = str(item.get("symbol", ""))
            if not symbol or "." in symbol:
                continue
            matches.append(
                SymbolMatch(
                    symbol=symbol,
                    name=str(item.get("description", symbol)).title(),
                    exchange=str(item.get("exchange", "")),
                )
            )
            if len(matches) >= limit:
                break
        return matches

    # ── Helpers ────────────────────────────────────────────────────────────
    def _safe_profile(self, symbol: str) -> CompanyProfile | None:
        try:
            data = self._get("/stock/profile2", {"symbol": symbol})
        except ProviderError:
            return None
        if not isinstance(data, dict) or not data.get("name"):
            return None
        cap = data.get("marketCapitalization")
        return CompanyProfile(
            symbol=symbol,
            name=str(data["name"]),
            exchange=str(data.get("exchange", "")),
            sector=str(data.get("finnhubIndustry", "")),
            currency=str(data.get("currency", "USD")),
            # Finnhub reports market cap in millions.
            market_cap=float(cap) * 1e6 if cap else None,
        )

    def _safe_metrics(self, symbol: str) -> dict:
        """Volume and 52-week range live on the /stock/metric endpoint."""
        try:
            data = self._get("/stock/metric", {"symbol": symbol, "metric": "all"})
        except ProviderError:
            return {}
        metric = data.get("metric", {}) if isinstance(data, dict) else {}
        avg_volume = metric.get("10DayAverageTradingVolume")
        return {
            "volume": None,  # not exposed on the free quote endpoint
            "avg_volume": float(avg_volume) * 1e6 if avg_volume else None,
            "week52_high": _opt_float(metric.get("52WeekHigh")),
            "week52_low": _opt_float(metric.get("52WeekLow")),
        }

    def close(self) -> None:
        self._client.close()


def _opt_float(value) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out != 0 else None
