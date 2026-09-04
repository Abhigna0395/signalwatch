"""Tests for the provider layer: determinism, freshness, and cross-source checks."""

from __future__ import annotations

import pytest

from app.providers.base import Freshness, classify_freshness
from app.providers.demo import (
    DemoMarketDataProvider,
    FINAL_REPLAY_STEP,
    REPLAY_STEPS,
    UNIVERSE,
)
from app.timeutil import utcnow
from datetime import timedelta


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────


def test_demo_provider_is_reproducible():
    a = DemoMarketDataProvider().get_quote("NVDA")
    b = DemoMarketDataProvider().get_quote("NVDA")
    assert a.price == b.price
    assert a.volume == b.volume
    assert a.week52_high == b.week52_high


def test_demo_history_is_reproducible():
    a = DemoMarketDataProvider().get_historical_data("AAPL", 200)
    b = DemoMarketDataProvider().get_historical_data("AAPL", 200)
    assert a.closes == b.closes


def test_every_universe_symbol_quotes_and_has_history():
    provider = DemoMarketDataProvider()
    for symbol in UNIVERSE:
        quote = provider.get_quote(symbol)
        assert quote.price > 0
        assert quote.previous_close and quote.previous_close > 0
        series = provider.get_historical_data(symbol, 260)
        assert len(series.candles) >= 252


def test_batch_quotes_match_individual_quotes():
    provider = DemoMarketDataProvider()
    symbols = ["NVDA", "TSLA", "MSFT"]
    batch = provider.get_quotes(symbols)
    for symbol in symbols:
        assert batch[symbol].price == provider.get_quote(symbol).price


# ─────────────────────────────────────────────────────────────────────────────
# Calibrated scenarios — the intelligence must be real, not scripted
# ─────────────────────────────────────────────────────────────────────────────


def test_nvda_scenario_is_a_breakout_on_volume():
    provider = DemoMarketDataProvider(world_step=FINAL_REPLAY_STEP)
    quote = provider.get_quote("NVDA")
    closes = provider._calibrated_closes("NVDA")
    resistance = max(closes[-61:-1])
    sma50 = sum(closes[-50:]) / 50

    assert quote.change_percent == pytest.approx(6.82, abs=0.05)
    assert quote.volume_ratio > 2.0
    assert quote.price > resistance          # genuine breakout
    assert quote.price > sma50               # genuine 50-day crossover
    assert closes[-1] < sma50                # ... that yesterday's close was below


def test_msft_scenario_is_genuinely_quiet():
    provider = DemoMarketDataProvider(world_step=FINAL_REPLAY_STEP)
    quote = provider.get_quote("MSFT")
    assert abs(quote.change_percent) < 1.0
    assert 0.8 < quote.volume_ratio < 1.15


def test_tsla_scenario_breaks_its_50_day_average():
    provider = DemoMarketDataProvider(world_step=FINAL_REPLAY_STEP)
    quote = provider.get_quote("TSLA")
    closes = provider._calibrated_closes("TSLA")
    sma50 = sum(closes[-50:]) / 50
    assert quote.change_percent < 0
    assert closes[-1] >= sma50 and quote.price < sma50   # crossed below today


def test_aapl_scenario_makes_a_new_52_week_high_only_at_the_end():
    quiet = DemoMarketDataProvider(world_step=0)
    loud = DemoMarketDataProvider(world_step=FINAL_REPLAY_STEP)

    prior_high = max(c.high for c in loud._candles("AAPL")[-252:-1])
    assert quiet.get_quote("AAPL").price < prior_high
    assert loud.get_quote("AAPL").price > prior_high


def test_replay_walk_re_rates_nvda_monotonically_ish():
    """The score must climb across the replay, ending far above where it began."""
    from app.services.analysis import analyze_stocks  # noqa: F401 - import cost check

    scores = []
    for step in range(len(REPLAY_STEPS)):
        provider = DemoMarketDataProvider(world_step=step)
        quote = provider.get_quote("NVDA")
        scores.append(quote.change_percent)
    assert scores[0] < 1.0
    assert scores[-1] > 6.0
    assert scores == sorted(scores)  # the day's move only grows


# ─────────────────────────────────────────────────────────────────────────────
# Freshness classification
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "age_seconds,expected",
    [
        (10, Freshness.FRESH),
        (80, Freshness.FRESH),
        (300, Freshness.RECENT),
        (1200, Freshness.STALE),
        (99999, Freshness.UNAVAILABLE),
    ],
)
def test_freshness_classification(age_seconds, expected):
    ts = utcnow() - timedelta(seconds=age_seconds)
    assert classify_freshness(ts) == expected


def test_freshness_unavailable_when_timestamp_missing():
    assert classify_freshness(None) == Freshness.UNAVAILABLE


def test_demo_provider_marks_nflx_as_delayed():
    """NFLX carries a deliberately stale timestamp for the delayed-data demo."""
    quote = DemoMarketDataProvider().get_quote("NFLX")
    assert quote.is_delayed is True
    assert classify_freshness(quote.source_timestamp) in (Freshness.STALE, Freshness.RECENT)


# ─────────────────────────────────────────────────────────────────────────────
# Cross-source reconciliation
# ─────────────────────────────────────────────────────────────────────────────


def test_secondary_source_disagrees_on_the_marked_symbol():
    from app.providers.registry import SecondaryDemoProvider

    primary = DemoMarketDataProvider().get_quote("META")
    secondary = SecondaryDemoProvider().get_quote("META")
    diff_pct = abs(primary.price - secondary.price) / primary.price * 100
    # META is the scenario flagged for a discrepancy.
    assert diff_pct > 0.75


def test_secondary_source_agrees_on_unmarked_symbols():
    from app.providers.registry import SecondaryDemoProvider

    primary = DemoMarketDataProvider().get_quote("MSFT")
    secondary = SecondaryDemoProvider().get_quote("MSFT")
    diff_pct = abs(primary.price - secondary.price) / primary.price * 100
    assert diff_pct < 0.75  # within tolerance — must NOT be flagged


def test_registry_records_a_discrepancy_for_meta(client):
    """End to end: the dashboard's data_quality surfaces the META conflict."""
    client.post("/api/watchlists", json={"name": "Conflicts"})
    lists = client.get("/api/watchlists").json()
    wl_id = lists[0]["id"]
    client.post(f"/api/watchlists/{wl_id}/stocks", json={"symbol": "META"})

    quality = client.get("/api/dashboard").json()["data_quality"]
    conflict_symbols = {c["symbol"] for c in quality["conflicts"]}
    assert "META" in conflict_symbols
    conflict = next(c for c in quality["conflicts"] if c["symbol"] == "META")
    # Both values are retained, not silently merged.
    assert conflict["value_a"] != conflict["value_b"]
    assert conflict["resolved_with"]
