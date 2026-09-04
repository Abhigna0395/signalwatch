"""Technical indicators.

Deliberately pure functions over plain lists: no pandas, no numpy, no provider
types. That keeps them trivially unit-testable and keeps the signal engine free
of hidden state. Every function tolerates short or empty input by returning
`None` rather than raising — a stock added seconds ago has no 50-day average,
and that is a normal condition, not an error.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def sma(values: list[float], period: int) -> float | None:
    """Simple moving average of the most recent `period` values."""
    if period <= 0 or len(values) < period:
        return None
    window = values[-period:]
    return sum(window) / period


def daily_returns(closes: list[float]) -> list[float]:
    """Simple period-over-period returns.

    Any interval touching a non-positive price is dropped rather than yielding a
    nonsense return (a print of 0 would otherwise register as a -100% day and
    then an undefined bounce).
    """
    out: list[float] = []
    for prev, curr in zip(closes, closes[1:]):
        if prev > 0 and curr > 0:
            out.append((curr - prev) / prev)
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI.

    Uses Wilder's smoothing (not a plain average of the last `period` moves),
    which is what charting packages actually display — a plain SMA of gains
    gives visibly different numbers and would make our "overbought" calls
    disagree with whatever the user is looking at elsewhere.
    """
    if len(closes) < period + 1:
        return None

    deltas = [b - a for a, b in zip(closes, closes[1:])]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for g, loss in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def realized_volatility(closes: list[float], period: int = 20, annualize: bool = True) -> float | None:
    """Rolling standard deviation of returns, annualised to a percentage."""
    rets = daily_returns(closes)
    if len(rets) < period or period < 2:
        return None
    window = rets[-period:]
    mean = sum(window) / len(window)
    variance = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
    vol = math.sqrt(variance)
    if annualize:
        vol *= math.sqrt(252)
    return vol * 100.0


def volume_ratio(current_volume: float | None, volumes: list[float], period: int = 20) -> float | None:
    """Today's volume as a multiple of its own recent average."""
    if current_volume is None or len(volumes) < period or period <= 0:
        return None
    avg = sum(volumes[-period:]) / period
    if avg <= 0:
        return None
    return current_volume / avg


def resistance(closes: list[float], lookback: int = 60) -> float | None:
    """Highest close over the lookback window, excluding the latest bar."""
    if len(closes) < 5:
        return None
    window = closes[-(lookback + 1):-1] or closes[:-1]
    return max(window) if window else None


def support(closes: list[float], lookback: int = 60) -> float | None:
    """Lowest close over the lookback window, excluding the latest bar."""
    if len(closes) < 5:
        return None
    window = closes[-(lookback + 1):-1] or closes[:-1]
    return min(window) if window else None


# A stock that has barely moved for twenty sessions produces a near-zero
# standard deviation, against which any ordinary move looks like a once-in-a-
# century event. Real quiet periods do this constantly (holiday weeks, halted
# names, tightly-pegged instruments). Flooring the estimate at a modest 0.35%
# daily and capping the resulting z keeps the "N× its typical range" phrasing
# defensible instead of letting it print absurdities.
_MIN_DAILY_SD = 0.0035
_MAX_ABS_ZSCORE = 6.0


def zscore_of_move(change_percent: float | None, closes: list[float], period: int = 20) -> float | None:
    """How unusual today's move is *for this stock*, in standard deviations.

    This is the difference between "the stock moved 3%" and "the stock moved
    3% when it normally moves 0.8%". A utility moving 3% is a far bigger event
    than a small-cap biotech doing the same, and the raw percentage cannot tell
    those apart. Everything downstream that talks about a "relative" move uses
    this rather than the headline percentage.
    """
    if change_percent is None:
        return None
    rets = daily_returns(closes)
    if len(rets) < period or period < 2:
        return None
    window = rets[-period:]
    mean = sum(window) / len(window)
    variance = sum((r - mean) ** 2 for r in window) / (len(window) - 1)
    sd = max(math.sqrt(variance), _MIN_DAILY_SD)
    z = ((change_percent / 100.0) - mean) / sd
    return max(-_MAX_ABS_ZSCORE, min(_MAX_ABS_ZSCORE, z))


@dataclass
class TechnicalState:
    """Everything the signal engine needs to know about one stock's chart.

    Computed once per stock per refresh and cached, rather than recomputed on
    every dashboard render (see README → Scalability).
    """

    sma20: float | None = None
    sma50: float | None = None
    rsi14: float | None = None
    volatility20: float | None = None
    volatility_baseline: float | None = None
    volume_ratio20: float | None = None
    resistance60: float | None = None
    support60: float | None = None
    move_zscore: float | None = None
    week52_high: float | None = None
    week52_low: float | None = None
    prev_close: float | None = None
    prev_sma20: float | None = None
    prev_sma50: float | None = None

    # ── Derived, human-meaningful regime flags ──────────────────────────────
    @property
    def rsi_zone(self) -> str:
        if self.rsi14 is None:
            return "unknown"
        if self.rsi14 >= 70:
            return "overbought"
        if self.rsi14 <= 30:
            return "oversold"
        return "neutral"

    @property
    def volatility_ratio(self) -> float | None:
        if not self.volatility_baseline or self.volatility20 is None:
            return None
        if self.volatility_baseline <= 0:
            return None
        return self.volatility20 / self.volatility_baseline

    def regime(self, price: float | None) -> dict:
        """A compact snapshot of technical state, stored on the user's baseline
        so we can later answer "has the regime *changed* since you last looked?"
        """
        return {
            "above_sma20": None if (price is None or self.sma20 is None) else price > self.sma20,
            "above_sma50": None if (price is None or self.sma50 is None) else price > self.sma50,
            "rsi_zone": self.rsi_zone,
            "above_resistance": (
                None if (price is None or self.resistance60 is None) else price > self.resistance60
            ),
            "below_support": (
                None if (price is None or self.support60 is None) else price < self.support60
            ),
        }


def compute_technical_state(
    closes: list[float],
    volumes: list[float],
    *,
    current_price: float | None,
    current_volume: float | None,
    change_percent: float | None,
    highs: list[float] | None = None,
    lows: list[float] | None = None,
) -> TechnicalState:
    """Build the full technical picture from a historical series plus today.

    `closes`/`volumes` are the *historical* bars (not including today), so the
    moving averages describe the state today's price is being compared against.

    `highs`/`lows` are optional but strongly preferred for the 52-week range.
    Measuring the yearly high from closes alone is far too lenient — a stock
    trades above its highest *close* on a routine day, so a close-based range
    would report a "new 52-week high" almost continuously. Falling back to
    closes is only for callers that genuinely have no intraday data.
    """
    state = TechnicalState(
        sma20=sma(closes, 20),
        sma50=sma(closes, 50),
        rsi14=rsi(closes + ([current_price] if current_price else []), 14),
        volatility20=realized_volatility(closes, 20),
        # Baseline = the longer-run volatility this stock normally runs at.
        volatility_baseline=realized_volatility(closes[:-20] if len(closes) > 120 else closes, 100),
        volume_ratio20=volume_ratio(current_volume, volumes, 20),
        resistance60=resistance(closes, 60),
        support60=support(closes, 60),
        move_zscore=zscore_of_move(change_percent, closes, 20),
        prev_close=closes[-1] if closes else None,
    )
    high_series = highs if highs else closes
    low_series = lows if lows else closes
    if high_series:
        state.week52_high = max(high_series[-252:])
    if low_series:
        state.week52_low = min(low_series[-252:])

    # Yesterday's averages, so we can detect a *crossover* rather than merely
    # observing which side of the line we are on today.
    if len(closes) >= 21:
        state.prev_sma20 = sma(closes[:-1], 20)
    if len(closes) >= 51:
        state.prev_sma50 = sma(closes[:-1], 50)
    return state
