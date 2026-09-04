"""Deterministic demo market data provider.

Why this exists
---------------
A hackathon demo that depends on a live third-party API is a demo that fails on
stage. This provider generates a *reproducible* market world from a fixed seed:
the same prices, the same volumes, the same news, every single run, with no
network and no API key.

It is not "fake data sprinkled through the UI" — it implements the same
`MarketDataProvider` interface as the live Finnhub provider and sits behind the
same registry, so the entire application above it is identical in both modes.
The UI always labels it clearly as DEMO DATA.

The world is deliberately *calibrated*, not merely random: each symbol carries a
`Scenario` that pins today's move, volume ratio, gap, and the exact relationship
between price and its moving averages / 52-week range. That way the signal
engine genuinely detects a breakout on NVDA and genuinely detects nothing on
MSFT — the intelligence is real, only the market is synthetic.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta

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

# ─────────────────────────────────────────────────────────────────────────────
# Scenario definition
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class NewsSeed:
    headline: str
    summary: str
    source: str
    topic: str
    minutes_ago: int


@dataclass
class Scenario:
    """A declarative description of the state we want the engine to detect."""

    change_percent: float = 0.3
    volume_ratio: float = 1.0
    gap_percent: float = 0.0
    # Where the previous close sits relative to its own 50-day SMA.
    # 0.985 => previous close 1.5% *below* the SMA, so a big up day crosses it.
    prev_close_vs_sma50: float = 1.02
    # 52-week high as a multiple of the previous close. 0.995 => today's move
    # into fresh highs. 1.10 => comfortably mid-range.
    high_ratio_252: float = 1.10
    low_ratio_252: float = 0.72
    # Multiplier applied to the most recent 20 days of returns, to create a
    # volatility expansion or contraction the engine can notice.
    recent_vol_multiplier: float = 1.0
    # Seconds of staleness on the quote timestamp — used to demo delayed data.
    stale_seconds: int = 0
    news: list[NewsSeed] = field(default_factory=list)
    # Percentage by which the *secondary* source disagrees, for the
    # discrepancy-detection demo. 0 => sources agree.
    secondary_disagreement_percent: float = 0.0


@dataclass
class SymbolSpec:
    name: str
    exchange: str
    sector: str
    currency: str
    base_price: float
    avg_volume: float
    market_cap: float
    annual_vol: float = 0.34
    drift: float = 0.10
    scenario: Scenario = field(default_factory=Scenario)


# ─────────────────────────────────────────────────────────────────────────────
# The universe
# ─────────────────────────────────────────────────────────────────────────────

_POS = "positive"
_NEG = "negative"

UNIVERSE: dict[str, SymbolSpec] = {
    # ── Scenario 1: large positive move + high volume + positive news ───────
    # NVDA is driven by the replay engine; the values below are its *final*
    # state (replay step 4). See REPLAY_STEPS.
    "NVDA": SymbolSpec(
        name="NVIDIA Corporation",
        exchange="NASDAQ",
        sector="Semiconductors",
        currency="USD",
        base_price=171.60,
        avg_volume=214_000_000,
        market_cap=4.19e12,
        annual_vol=0.46,
        drift=0.38,
        scenario=Scenario(
            change_percent=6.82,
            volume_ratio=2.41,
            gap_percent=1.9,
            # A two-month consolidation that slipped just under its 50-day
            # average, with the range top ~6.1% overhead and the yearly high
            # 8.5% away. Today's move is therefore a genuine range breakout *and*
            # a 50-day crossover, without taking out the 52-week high — AAPL owns
            # the new-high scenario. The replay frames land the crossovers at
            # step 2 and the breakout at step 4, so the score builds in stages
            # rather than arriving all at once.
            prev_close_vs_sma50=0.982,
            high_ratio_252=1.045,
            low_ratio_252=0.92,
            # A range breakout on 2.4× volume genuinely expands realised
            # volatility, so this is set to produce a measured ~1.5× expansion.
            # Note the multiplier is not the measured ratio: the 5-day trend
            # split absorbs part of each shock, so it takes ~2.6 here to show
            # ~1.5 downstream. Applied from replay step 2, when the move begins.
            recent_vol_multiplier=2.6,
            news=[
                NewsSeed(
                    "NVIDIA lands multi-year accelerator supply agreement with major cloud provider",
                    "The agreement covers next-generation data-centre GPUs and is expected to "
                    "contribute to revenue from the second half of the fiscal year.",
                    "Market Wire", "AI Demand", 12,
                ),
                NewsSeed(
                    "Analysts raise NVIDIA targets on stronger data-centre demand outlook",
                    "Several research desks lifted price targets, citing improved visibility on "
                    "accelerator orders and easing supply constraints.",
                    "Street Research", "AI Demand", 47,
                ),
                NewsSeed(
                    "Data-centre GPU shipments beat prior guidance, supply chain checks suggest",
                    "Channel checks point to shipment volumes running ahead of the company's own "
                    "prior guidance for the quarter.",
                    "Supply Chain Daily", "AI Demand", 96,
                ),
            ],
        ),
    ),
    # ── Scenario 2: negative move + technical breakdown + negative news ────
    "TSLA": SymbolSpec(
        name="Tesla, Inc.",
        exchange="NASDAQ",
        sector="Automotive",
        currency="USD",
        base_price=402.10,
        avg_volume=92_000_000,
        market_cap=1.29e12,
        annual_vol=0.52,
        drift=-0.16,
        scenario=Scenario(
            change_percent=-2.74,
            volume_ratio=1.44,
            gap_percent=-0.9,
            prev_close_vs_sma50=1.004,   # sitting on the average, today breaks it
            high_ratio_252=1.24,
            low_ratio_252=0.86,
            recent_vol_multiplier=1.2,
            news=[
                NewsSeed(
                    "Tesla deliveries miss estimates as two brokerages downgrade the stock",
                    "Analysts cut price targets, citing weak order intake in Europe and a "
                    "softer demand outlook into the next quarter.",
                    "Auto Analyst", "Deliveries", 38,
                ),
                NewsSeed(
                    "Tesla deliveries fall short again; brokerage lowers full-year forecast",
                    "The downgrade follows a third round of European price reductions that "
                    "analysts warn will pressure margins and weaken profitability.",
                    "Global Auto Review", "Deliveries", 140,
                ),
                NewsSeed(
                    "Regulators open a probe into Tesla driver-assistance software",
                    "The investigation adds regulatory risk on top of an already weak "
                    "delivery picture, analysts said.",
                    "Reg Watch", "Regulatory", 260,
                ),
            ],
        ),
    ),
    # ── Scenario 3: nothing happened. The control case. ────────────────────
    "MSFT": SymbolSpec(
        name="Microsoft Corporation",
        exchange="NASDAQ",
        sector="Software",
        currency="USD",
        base_price=511.30,
        avg_volume=21_500_000,
        market_cap=3.80e12,
        annual_vol=0.22,
        drift=0.14,
        scenario=Scenario(
            change_percent=0.42,
            volume_ratio=0.94,
            prev_close_vs_sma50=1.018,
            high_ratio_252=1.07,
        ),
    ),
    # ── Scenario 4: moderate move into a new 52-week high ──────────────────
    "AAPL": SymbolSpec(
        name="Apple Inc.",
        exchange="NASDAQ",
        sector="Consumer Electronics",
        currency="USD",
        base_price=268.90,
        avg_volume=48_000_000,
        market_cap=3.98e12,
        annual_vol=0.26,
        drift=0.18,
        scenario=Scenario(
            change_percent=1.94,
            volume_ratio=1.58,
            prev_close_vs_sma50=1.031,
            # Calibrated so the prior 52-week high sits just under today's
            # target price: the stock reaches fresh highs only once the full
            # +1.94% has played out, and not at any earlier replay frame.
            high_ratio_252=0.96,
            low_ratio_252=0.84,
            news=[
                NewsSeed(
                    "Services revenue run-rate reaches a new quarterly record",
                    "Growth was led by subscriptions and payments, according to the disclosure.",
                    "Tech Ledger", "Services Growth", 74,
                ),
            ],
        ),
    ),
    # ── Scenario 5: volume anomaly with almost no price move (divergence) ──
    "AMZN": SymbolSpec(
        name="Amazon.com, Inc.",
        exchange="NASDAQ",
        sector="E-Commerce",
        currency="USD",
        base_price=232.40,
        avg_volume=39_000_000,
        market_cap=2.47e12,
        annual_vol=0.30,
        drift=0.12,
        scenario=Scenario(
            change_percent=0.58,
            volume_ratio=3.12,          # 3.1x volume on a flat tape
            prev_close_vs_sma50=1.006,
            high_ratio_252=1.05,
        ),
    ),
    # ── Supporting cast ────────────────────────────────────────────────────
    "GOOGL": SymbolSpec(
        name="Alphabet Inc.",
        exchange="NASDAQ",
        sector="Internet",
        currency="USD",
        base_price=283.15,
        avg_volume=27_000_000,
        market_cap=3.42e12,
        annual_vol=0.27,
        drift=0.16,
        scenario=Scenario(change_percent=0.31, volume_ratio=0.88, prev_close_vs_sma50=1.021),
    ),
    # Cross-source disagreement + volatility expansion.
    "META": SymbolSpec(
        name="Meta Platforms, Inc.",
        exchange="NASDAQ",
        sector="Internet",
        currency="USD",
        base_price=642.80,
        avg_volume=14_800_000,
        market_cap=1.62e12,
        annual_vol=0.33,
        drift=0.09,
        scenario=Scenario(
            change_percent=-1.12,
            volume_ratio=1.22,
            prev_close_vs_sma50=1.009,
            recent_vol_multiplier=2.05,          # volatility expansion
            secondary_disagreement_percent=2.9,  # sources disagree → flagged
        ),
    ),
    "AMD": SymbolSpec(
        name="Advanced Micro Devices, Inc.",
        exchange="NASDAQ",
        sector="Semiconductors",
        currency="USD",
        base_price=214.70,
        avg_volume=41_000_000,
        market_cap=3.48e11,
        annual_vol=0.48,
        drift=0.20,
        scenario=Scenario(
            change_percent=3.41,
            volume_ratio=1.92,
            gap_percent=2.83,            # gap up
            prev_close_vs_sma50=1.012,
            high_ratio_252=1.06,
            low_ratio_252=0.80,
        ),
    ),
    # Deliberately stale quote — demonstrates the delayed-data path.
    "NFLX": SymbolSpec(
        name="Netflix, Inc.",
        exchange="NASDAQ",
        sector="Media",
        currency="USD",
        base_price=1094.20,
        avg_volume=3_400_000,
        market_cap=4.66e11,
        annual_vol=0.35,
        drift=0.11,
        scenario=Scenario(
            change_percent=-0.94,
            volume_ratio=1.05,
            prev_close_vs_sma50=1.014,
            stale_seconds=1320,          # 22 minutes old
        ),
    ),
    "JPM": SymbolSpec(
        name="JPMorgan Chase & Co.",
        exchange="NYSE",
        sector="Banking",
        currency="USD",
        base_price=318.60,
        avg_volume=8_900_000,
        market_cap=8.85e11,
        annual_vol=0.21,
        drift=0.13,
        scenario=Scenario(change_percent=0.17, volume_ratio=0.91, prev_close_vs_sma50=1.016),
    ),
    # ── Indian equities (INR) — the app is currency-aware end to end ───────
    "RELIANCE": SymbolSpec(
        name="Reliance Industries Limited",
        exchange="NSE",
        sector="Energy",
        currency="INR",
        base_price=1502.40,
        avg_volume=11_200_000,
        market_cap=2.03e13,
        annual_vol=0.24,
        drift=0.11,
        scenario=Scenario(
            change_percent=2.31,
            volume_ratio=1.74,
            prev_close_vs_sma50=0.994,   # crosses back above the 50-day
            high_ratio_252=1.04,
            news=[
                NewsSeed(
                    "Retail arm reports faster store additions than planned",
                    "Expansion is running ahead of the internal plan for the half-year.",
                    "Business Standard Wire", "Retail Expansion", 55,
                ),
            ],
        ),
    ),
    "TCS": SymbolSpec(
        name="Tata Consultancy Services Limited",
        exchange="NSE",
        sector="Information Technology",
        currency="INR",
        base_price=3184.90,
        avg_volume=3_100_000,
        market_cap=1.15e13,
        annual_vol=0.19,
        drift=0.04,
        scenario=Scenario(
            change_percent=-1.42,
            volume_ratio=1.18,
            prev_close_vs_sma50=1.002,
            low_ratio_252=0.93,
        ),
    ),
    "INFY": SymbolSpec(
        name="Infosys Limited",
        exchange="NSE",
        sector="Information Technology",
        currency="INR",
        base_price=1571.20,
        avg_volume=7_400_000,
        market_cap=6.52e12,
        annual_vol=0.22,
        drift=0.07,
        scenario=Scenario(change_percent=0.83, volume_ratio=1.11, prev_close_vs_sma50=1.024),
    ),
    "HDFCBANK": SymbolSpec(
        name="HDFC Bank Limited",
        exchange="NSE",
        sector="Banking",
        currency="INR",
        base_price=1988.50,
        avg_volume=9_600_000,
        market_cap=1.52e13,
        annual_vol=0.18,
        drift=0.09,
        scenario=Scenario(change_percent=0.29, volume_ratio=0.97, prev_close_vs_sma50=1.011),
    ),
}


# ─────────────────────────────────────────────────────────────────────────────
# The replay script (Scenario 23 in the brief)
#
# Each step is a *complete world state* for NVDA, not an animation. Advancing
# the step changes what the provider returns, the signal engine re-detects from
# scratch, and the score genuinely moves 31 → 82.
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ReplayStep:
    clock: str
    caption: str
    change_percent: float
    volume_ratio: float
    news_count: int


REPLAY_STEPS: list[ReplayStep] = [
    ReplayStep("10:02 AM", "NVDA stable — nothing to see", 0.34, 0.92, 0),
    ReplayStep("10:18 AM", "Volume begins to build", 1.15, 1.88, 0),
    ReplayStep("10:21 AM", "Price accelerates on heavy volume", 4.21, 2.19, 1),
    ReplayStep("10:23 AM", "News activity increases", 5.63, 2.34, 3),
    ReplayStep("10:25 AM", "Breakout confirmed — attention re-rates", 6.82, 2.41, 3),
]

REPLAY_SYMBOL = "NVDA"
FINAL_REPLAY_STEP = len(REPLAY_STEPS) - 1

# How far each non-NVDA scenario has played out at each replay frame. Frame 0 is
# the quiet open; frame 4 is the fully-developed session described by each
# symbol's `Scenario`.
_SESSION_PROGRESS = [0.06, 0.22, 0.55, 0.82, 1.0]


# ─────────────────────────────────────────────────────────────────────────────
# Provider
# ─────────────────────────────────────────────────────────────────────────────

_TRADING_DAYS_PER_YEAR = 252

# Memoised deterministic series, keyed by (symbol, bars, world_step, offset).
# The world only changes when the replay step advances, so this is small and
# never needs invalidating beyond a process restart.
_CANDLE_CACHE: dict[tuple, list[Candle]] = {}


def _smooth(values: list[float], window: int) -> list[float]:
    """Centred moving average, with the window shrinking at the edges."""
    n = len(values)
    half = window // 2
    out: list[float] = []
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        chunk = values[lo:hi]
        out.append(sum(chunk) / len(chunk))
    return out


class DemoMarketDataProvider(MarketDataProvider):
    name = "demo"
    is_demo = True

    def __init__(self, world_step: int = FINAL_REPLAY_STEP, *, source_label: str | None = None,
                 price_offset_percent: float = 0.0):
        """`world_step` selects the replay frame. `price_offset_percent` lets the
        registry instantiate a *second*, slightly different view of the same
        world to exercise cross-source comparison."""
        self.world_step = max(0, min(world_step, FINAL_REPLAY_STEP))
        self.name = source_label or self.name
        self.price_offset_percent = price_offset_percent

    # ── Scenario resolution ────────────────────────────────────────────────
    def _spec(self, symbol: str) -> SymbolSpec:
        spec = UNIVERSE.get(symbol.upper())
        if spec is None:
            raise ProviderError(self.name, f"Unknown symbol '{symbol}' in the demo universe")
        return spec

    def _scenario(self, symbol: str) -> Scenario:
        """Resolve the scenario for the current replay frame.

        The replay is a single trading day progressing, not a spotlight on one
        stock. NVDA follows its own scripted arc (below); every other symbol has
        its move, volume and news scaled by how far into the session we are.

        That matters for more than presentation. If only NVDA changed between
        frames, then seeding a baseline at frame 0 would produce exactly one
        "since your last visit" card, and the feature would look thin. Scaling
        the whole world means every scenario — TSLA's breakdown, AAPL's new
        high, AMZN's volume anomaly — genuinely *develops* while the user is
        away, and is genuinely detected on their return.

        Structural properties are deliberately *not* scaled: the moving
        averages, the 52-week range and the volatility regime describe months of
        history and have no business changing during a session.
        """
        symbol = symbol.upper()
        spec = self._spec(symbol)
        base = spec.scenario

        if symbol != REPLAY_SYMBOL:
            progress = _SESSION_PROGRESS[self.world_step]
            return Scenario(
                change_percent=base.change_percent * progress,
                volume_ratio=1.0 + (base.volume_ratio - 1.0) * progress,
                gap_percent=base.gap_percent * progress,
                prev_close_vs_sma50=base.prev_close_vs_sma50,
                high_ratio_252=base.high_ratio_252,
                low_ratio_252=base.low_ratio_252,
                recent_vol_multiplier=base.recent_vol_multiplier,
                stale_seconds=base.stale_seconds,
                news=base.news[: round(len(base.news) * progress)],
                secondary_disagreement_percent=base.secondary_disagreement_percent,
            )

        step = REPLAY_STEPS[self.world_step]
        # Copy the static parts, override the parts the replay drives.
        return Scenario(
            change_percent=step.change_percent,
            volume_ratio=step.volume_ratio,
            gap_percent=base.gap_percent if self.world_step >= 2 else 0.15,
            prev_close_vs_sma50=base.prev_close_vs_sma50,
            high_ratio_252=base.high_ratio_252,
            low_ratio_252=base.low_ratio_252,
            recent_vol_multiplier=base.recent_vol_multiplier if self.world_step >= 2 else 1.0,
            stale_seconds=base.stale_seconds,
            news=base.news[: step.news_count],
            secondary_disagreement_percent=base.secondary_disagreement_percent,
        )

    # ── Deterministic series construction ──────────────────────────────────
    def _rng(self, symbol: str, salt: str = "") -> random.Random:
        # A fixed, explicit seed — never `hash()`, which is salted per process.
        seed = sum(ord(c) * (i + 7) for i, c in enumerate(f"{symbol}|{salt}"))
        return random.Random(seed)

    def _raw_closes(self, symbol: str, n: int) -> list[float]:
        """Geometric random walk with a scenario-controlled recent-vol regime."""
        spec = self._spec(symbol)
        scenario = self._scenario(symbol)
        rng = self._rng(symbol, "closes")

        daily_drift = spec.drift / _TRADING_DAYS_PER_YEAR
        daily_vol = spec.annual_vol / math.sqrt(_TRADING_DAYS_PER_YEAR)

        log_price = math.log(spec.base_price)
        closes: list[float] = []
        for i in range(n):
            # A gentle multi-month cycle keeps the chart from looking like noise.
            cycle = 0.0016 * math.sin(2 * math.pi * i / 84.0)
            vol = daily_vol
            if i >= n - 20:
                vol *= scenario.recent_vol_multiplier
            shock = rng.gauss(0.0, 1.0) * vol
            log_price += daily_drift + cycle + shock
            closes.append(math.exp(log_price))
        return closes

    def _calibrated_closes(self, symbol: str, n: int = 400) -> list[float]:
        """Bend the random walk until it satisfies the scenario's constraints.

        Two constraints matter to the signal engine:
          1. where the previous close sits relative to its own 50-day SMA, and
          2. where the 52-week high/low sit relative to that previous close.

        Both are *ratios*, so uniformly rescaling the series cannot satisfy (2)
        — the scale factor cancels on both sides. The range has to be reshaped,
        not resized. So we scale the history's deviations around its median:
        values above the median move toward or away from it until the maximum
        lands on target, and likewise below for the minimum. That preserves the
        shape of the walk (no flat clipped plateaus) while relocating extremes.

        Reshaping perturbs the 50-day mean, which moves constraint (1). The two
        are therefore solved as a **fixed point**: every iteration re-derives
        the transform from the *pristine* raw walk rather than compounding onto
        the previous pass. That distinction matters — compounding the transform
        makes the scale factor reappear on both sides each round and the series
        marches off to infinity, whereas the fixed-point form is a contraction
        (empirically |slope| ~ 0.2) and settles in a handful of passes.

        Finally the whole series is rescaled so the last close lands on the
        symbol's configured base price. That last step is a *uniform* scaling,
        so it leaves both ratio constraints exactly intact while keeping quoted
        prices in a realistic range instead of wherever 400 days of compounded
        drift happened to end up.
        """
        scenario = self._scenario(symbol)
        raw = self._raw_closes(symbol, n)
        r = scenario.prev_close_vs_sma50

        # Split the walk into a slow trend and the daily noise riding on it.
        #
        # This matters more than it looks. The reshape below compresses
        # deviations toward a pivot, and applied to the raw series it squeezes
        # *day-to-day* variation too — flattening realised volatility, which in
        # turn made the move z-score explode (a 6.8% move against an
        # artificially tiny standard deviation reads as "12× normal") and made
        # the scenario's volatility knob do nothing. Reshaping only the trend
        # and multiplying the untouched noise back on top relocates the price
        # range while leaving the daily return distribution exactly as
        # generated.
        trend = _smooth(raw, 5)
        noise = [raw[i] / trend[i] if trend[i] else 1.0 for i in range(n)]

        # Fixed reference points, computed once from the untouched trend.
        trend_hist = trend[-_TRADING_DAYS_PER_YEAR:-1]
        pivot = sorted(trend_hist)[len(trend_hist) // 2]
        trend_hi, trend_lo = max(trend_hist), min(trend_hist)

        # A fixed price anchor for the reshape targets. Anchoring to the raw
        # walk's own last value — rather than to the previous close we are still
        # solving for — is what decouples the two constraints. With the history
        # no longer a function of P, the SMA constraint stops being a fixed
        # point and becomes a single closed-form assignment that is exact by
        # construction on every pass. (An earlier version did make the reshape
        # depend on P; the resulting feedback loop diverged outright for symbols
        # whose recent bars sat near their yearly high.)
        ref = raw[-1]

        def build(hi_ratio: float, lo_ratio: float) -> list[float]:
            target_hi = ref * hi_ratio
            target_lo = ref * lo_ratio
            # The pivot has to sit safely *below* the target high, otherwise the
            # upper half of the distribution would have to fold over itself and
            # the scale factor goes negative. A walk that ended in a deep
            # drawdown (NVDA: the year's median is 21% above its last close)
            # puts the raw median above the target, so clamp the pivot into the
            # lower part of the target band. This is what keeps the transform a
            # genuine monotone rescale rather than a collapse.
            p = min(pivot, target_lo + 0.55 * (target_hi - target_lo))
            up = (target_hi - p) / (trend_hi - p) if trend_hi > p else 1.0
            down = (p - target_lo) / (p - trend_lo) if trend_lo < p else 1.0
            hist = [
                (p + (trend[i] - p) * (up if trend[i] >= p else down)) * noise[i]
                for i in range(n - 1)
            ]
            # P = r·(A + P)/50  =>  P = r·A/(50 − r), with A now a constant.
            return [*hist, r * sum(hist[-49:]) / (50.0 - r)]

        # Outer correction. The reshape targets the *trend's* extremes, but the
        # series we publish is trend × noise, and noise lifts the peaks a couple
        # of percent above where the trend alone would land — and the previous
        # close lands wherever the SMA constraint puts it. Rather than modelling
        # either analytically, measure the achieved ratios and rescale the
        # targets. Each pass is exact in the SMA and multiplicatively corrective
        # in the range, so it settles in two or three rounds.
        # The correction is damped with a square root and the ratios are kept in
        # a sane band. An undamped multiplicative step overshoots badly whenever
        # the pivot clamp toggles between passes — the response is piecewise, not
        # smooth — and an undamped run diverged to 3.6× on some symbols. Halving
        # each step in log space trades two extra passes for reliable
        # convergence, which is the right trade for something that runs once per
        # symbol and is then cached.
        hi_ratio, lo_ratio = scenario.high_ratio_252, scenario.low_ratio_252
        closes = build(hi_ratio, lo_ratio)
        best = closes
        best_error = float("inf")

        for _ in range(14):
            prev_close = closes[-1]
            window = closes[-_TRADING_DAYS_PER_YEAR:-1]
            achieved_hi = max(window) / prev_close
            achieved_lo = min(window) / prev_close

            error = abs(achieved_hi - scenario.high_ratio_252)
            if error < best_error:
                best_error, best = error, closes
            if error < 0.001 and abs(achieved_lo - scenario.low_ratio_252) < 0.004:
                break

            if achieved_hi > 0:
                hi_ratio *= math.sqrt(scenario.high_ratio_252 / achieved_hi)
            if achieved_lo > 0:
                lo_ratio *= math.sqrt(scenario.low_ratio_252 / achieved_lo)
            hi_ratio = max(0.85, min(hi_ratio, 1.9))
            lo_ratio = max(0.30, min(lo_ratio, 0.99))
            closes = build(hi_ratio, lo_ratio)

        # Keep the best pass rather than the last, so a late oscillation can
        # never make the result worse than one we already found.
        closes = best if best_error < abs(
            max(closes[-_TRADING_DAYS_PER_YEAR:-1]) / closes[-1] - scenario.high_ratio_252
        ) else closes

        # Uniform rescale onto a realistic price level. Ratio-preserving, so it
        # cannot disturb either constraint.
        spec = self._spec(symbol)
        factor = spec.base_price / closes[-1]
        return [c * factor for c in closes]

    def _candles(self, symbol: str, n: int = 400) -> list[Candle]:
        # Series construction is pure and deterministic, but not free (a 400-bar
        # walk plus a 40-pass fixed point). Every dashboard render asks for the
        # same handful of symbols, so memoise on the inputs that define the
        # world: the symbol, the replay step and the source offset.
        key = (symbol.upper(), n, self.world_step, self.price_offset_percent)
        cached = _CANDLE_CACHE.get(key)
        if cached is not None:
            return cached

        spec = self._spec(symbol)
        closes = self._calibrated_closes(symbol, n)
        rng = self._rng(symbol, "bars")

        # Trading days only — walk backwards from yesterday, skipping weekends.
        days: list[date] = []
        cursor = utcnow().date() - timedelta(days=1)
        while len(days) < n:
            if cursor.weekday() < 5:
                days.append(cursor)
            cursor -= timedelta(days=1)
        days.reverse()

        candles: list[Candle] = []
        prev_close = closes[0]
        for i, (day, close) in enumerate(zip(days, closes)):
            intraday = abs(rng.gauss(0.0, 0.006)) + 0.002
            open_ = prev_close * (1 + rng.gauss(0.0, 0.003))
            high = max(open_, close) * (1 + intraday)
            low = min(open_, close) * (1 - intraday)
            # Volume mean-reverts around the symbol's average with fat tails.
            vol_noise = math.exp(rng.gauss(0.0, 0.28))
            volume = spec.avg_volume * vol_noise
            if i >= n - 20:
                volume *= 1.0 + 0.15 * math.sin(i / 3.0)
            candles.append(
                Candle(day=day, open=round(open_, 4), high=round(high, 4),
                       low=round(low, 4), close=round(close, 4), volume=round(volume))
            )
            prev_close = close

        _CANDLE_CACHE[key] = candles
        return candles

    # ── MarketDataProvider implementation ──────────────────────────────────
    def get_quote(self, symbol: str) -> Quote:
        symbol = symbol.upper()
        spec = self._spec(symbol)
        scenario = self._scenario(symbol)
        candles = self._candles(symbol)

        previous_close = candles[-1].close
        price = previous_close * (1 + scenario.change_percent / 100.0)
        price *= 1 + self.price_offset_percent / 100.0
        open_ = previous_close * (1 + scenario.gap_percent / 100.0)

        recent_vols = [c.volume for c in candles[-20:]]
        avg_volume = sum(recent_vols) / len(recent_vols)
        volume = avg_volume * scenario.volume_ratio

        window = [c for c in candles[-_TRADING_DAYS_PER_YEAR:]]
        week52_high = max(max(c.high for c in window), price)
        week52_low = min(min(c.low for c in window), price)

        day_high = max(price, open_, previous_close) * 1.004
        day_low = min(price, open_, previous_close) * 0.996

        rng = self._rng(symbol, f"age{self.world_step}")
        age = scenario.stale_seconds or rng.randint(8, 55)

        return Quote(
            symbol=symbol,
            price=round(price, 2),
            previous_close=round(previous_close, 2),
            open=round(open_, 2),
            day_high=round(day_high, 2),
            day_low=round(day_low, 2),
            volume=round(volume),
            avg_volume=round(avg_volume),
            market_cap=spec.market_cap * (price / spec.base_price),
            week52_high=round(week52_high, 2),
            week52_low=round(week52_low, 2),
            currency=spec.currency,
            source=self.name,
            source_timestamp=utcnow() - timedelta(seconds=age),
            is_delayed=scenario.stale_seconds > 0,
        )

    def get_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        # The demo provider is genuinely batch-capable: no per-symbol I/O.
        out: dict[str, Quote] = {}
        for symbol in symbols:
            try:
                out[symbol.upper()] = self.get_quote(symbol)
            except ProviderError:
                continue
        return out

    def get_historical_data(self, symbol: str, days: int = 400) -> HistoricalSeries:
        symbol = symbol.upper()
        candles = self._candles(symbol)[-days:]
        return HistoricalSeries(
            symbol=symbol, candles=candles, source=self.name, source_timestamp=utcnow()
        )

    def get_news(self, symbol: str, limit: int = 20) -> list[NewsArticle]:
        symbol = symbol.upper()
        scenario = self._scenario(symbol)
        now = utcnow()
        articles = []
        for i, seed in enumerate(scenario.news[:limit]):
            articles.append(
                NewsArticle(
                    symbol=symbol,
                    external_id=f"demo-{symbol}-{i}-{seed.topic.replace(' ', '')}",
                    headline=seed.headline,
                    summary=seed.summary,
                    source=seed.source,
                    url="",
                    published_at=now - timedelta(minutes=seed.minutes_ago),
                )
            )
        return articles

    def get_company_profile(self, symbol: str) -> CompanyProfile:
        symbol = symbol.upper()
        spec = self._spec(symbol)
        return CompanyProfile(
            symbol=symbol,
            name=spec.name,
            exchange=spec.exchange,
            sector=spec.sector,
            currency=spec.currency,
            market_cap=spec.market_cap,
        )

    def search_symbols(self, query: str, limit: int = 10) -> list[SymbolMatch]:
        q = query.strip().lower()
        if not q:
            return []
        scored: list[tuple[int, SymbolMatch]] = []
        for symbol, spec in UNIVERSE.items():
            sym_l, name_l = symbol.lower(), spec.name.lower()
            if sym_l == q:
                rank = 0
            elif sym_l.startswith(q):
                rank = 1
            elif name_l.startswith(q):
                rank = 2
            elif q in name_l:
                rank = 3
            elif q in sym_l:
                rank = 4
            else:
                continue
            scored.append(
                (rank, SymbolMatch(symbol=symbol, name=spec.name,
                                   exchange=spec.exchange, currency=spec.currency))
            )
        scored.sort(key=lambda t: (t[0], t[1].symbol))
        return [m for _, m in scored[:limit]]

    # ── Demo-only helpers ──────────────────────────────────────────────────
    def secondary_disagreement_percent(self, symbol: str) -> float:
        return self._scenario(symbol.upper()).secondary_disagreement_percent
