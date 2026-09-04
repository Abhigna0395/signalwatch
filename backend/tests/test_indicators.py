"""Unit tests for the technical indicator functions."""

from __future__ import annotations

import math

import pytest

from app.services.indicators import (
    compute_technical_state,
    daily_returns,
    realized_volatility,
    rsi,
    sma,
    support,
    resistance,
    volume_ratio,
    zscore_of_move,
)


def test_sma_needs_a_full_window():
    assert sma([1, 2, 3], 5) is None
    assert sma([1, 2, 3, 4, 5], 5) == 3.0
    assert sma([2, 4, 6, 8], 2) == 7.0


def test_rsi_all_gains_saturates_high():
    assert rsi([float(i) for i in range(1, 30)], 14) == pytest.approx(100.0)


def test_rsi_all_losses_saturates_low():
    assert rsi([float(i) for i in range(30, 1, -1)], 14) == pytest.approx(0.0)


def test_rsi_is_in_range_for_mixed_series():
    closes = [10 + 3 * math.sin(i / 2) for i in range(60)]
    value = rsi(closes, 14)
    assert value is not None
    assert 0 <= value <= 100


def test_rsi_returns_none_on_short_input():
    assert rsi([1, 2, 3], 14) is None


def test_volume_ratio():
    assert volume_ratio(2_000_000, [1_000_000] * 20, 20) == pytest.approx(2.0)
    assert volume_ratio(None, [1] * 20) is None
    assert volume_ratio(5, [1] * 5, 20) is None  # not enough history


def test_realized_volatility_is_annualised_percentage():
    # A steady 1%/day series has ~0 volatility.
    steady = [100 * (1.01**i) for i in range(40)]
    vol = realized_volatility(steady, 20)
    assert vol is not None
    assert vol < 1.0  # near zero, but positive


def test_zscore_flags_an_unusual_move():
    # Twenty days of ~0.3% moves, then a 4% day.
    closes = [100.0]
    for _ in range(25):
        closes.append(closes[-1] * 1.003)
    z = zscore_of_move(4.0, closes, 20)
    assert z is not None
    assert z > 2.5


def test_zscore_is_clamped_for_a_degenerate_series():
    """A frozen price must not turn any move into a 100-sigma event."""
    flat = [100.0] * 40
    z = zscore_of_move(3.0, flat, 20)
    assert z is not None
    assert abs(z) <= 6.0 + 1e-9


def test_support_and_resistance_exclude_the_latest_bar():
    closes = [100, 101, 99, 103, 98, 105]  # last bar is the max
    assert resistance(closes, 60) == 103  # excludes the 105
    assert support(closes, 60) == 98


def test_compute_technical_state_uses_intraday_range_for_52w():
    closes = [100.0 + i * 0.1 for i in range(300)]
    highs = [c + 5 for c in closes]  # intraday highs run well above closes
    lows = [c - 5 for c in closes]
    state = compute_technical_state(
        closes, [1_000_000] * 300,
        current_price=closes[-1], current_volume=1_000_000, change_percent=0.1,
        highs=highs, lows=lows,
    )
    # The 52-week high must come from `highs`, not `closes`.
    assert state.week52_high == pytest.approx(max(highs[-252:]))
    assert state.week52_high > max(closes)


def test_technical_state_regime_snapshot():
    closes = [100.0] * 60
    state = compute_technical_state(
        closes, [1_000_000] * 60,
        current_price=105.0, current_volume=1_000_000, change_percent=5.0,
    )
    regime = state.regime(105.0)
    assert regime["above_sma20"] is True
    assert regime["above_resistance"] is True


def test_daily_returns_skips_non_positive_prices():
    assert daily_returns([100, 110, 0, 50]) == pytest.approx([0.1])


def test_indicators_tolerate_empty_input():
    assert sma([], 5) is None
    assert rsi([], 14) is None
    assert realized_volatility([], 20) is None
    assert resistance([], 60) is None
