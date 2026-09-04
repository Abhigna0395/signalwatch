"""The Meaningful Change Engine.

This is the product. Everything else is plumbing around it.

Two design rules govern this module:

1. **It is a pure function.** No database, no HTTP, no clock reads beyond what
   is passed in. `evaluate()` takes a fully-formed `SignalInput` and returns a
   `SignalResult`. That is what makes the scoring genuinely testable, and it is
   why the tests can assert "this exact market state produces this exact score"
   rather than "the endpoint returned 200".

2. **Nothing is unexplained.** There is no opaque model. The score is a sum of
   six bounded components, each of which reports its own inputs, its own
   arithmetic, and a sentence a human can read. If the UI shows 82, this module
   can say precisely which points came from where, and removing any component
   changes the number in a way you can predict.

The weights are configuration (`app/config.py`), not literals, so the scoring
policy can be retuned without touching detection logic.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.config import AttentionWeights, settings
from app.services.indicators import TechnicalState
from app.timeutil import age_seconds, utcnow


# ─────────────────────────────────────────────────────────────────────────────
# Vocabulary
# ─────────────────────────────────────────────────────────────────────────────


class EventType(str, Enum):
    PRICE_MOVE = "PRICE_MOVE"
    GAP_UP = "GAP_UP"
    GAP_DOWN = "GAP_DOWN"
    NEW_HIGH = "NEW_HIGH"
    NEW_LOW = "NEW_LOW"
    VOLUME_SPIKE = "VOLUME_SPIKE"
    VOLUME_DIVERGENCE = "VOLUME_DIVERGENCE"
    MA_CROSSOVER = "MA_CROSSOVER"
    BREAKOUT = "BREAKOUT"
    BREAKDOWN = "BREAKDOWN"
    RSI_REGIME_CHANGE = "RSI_REGIME_CHANGE"
    VOLATILITY_SPIKE = "VOLATILITY_SPIKE"
    NEWS_SPIKE = "NEWS_SPIKE"
    NEWS_SENTIMENT_SHIFT = "NEWS_SENTIMENT_SHIFT"
    USER_THRESHOLD = "USER_THRESHOLD"
    SINCE_VISIT_MOVE = "SINCE_VISIT_MOVE"
    DATA_QUALITY_WARNING = "DATA_QUALITY_WARNING"


class Category(str, Enum):
    PRICE = "PRICE"
    VOLUME = "VOLUME"
    TECHNICAL = "TECHNICAL"
    NEWS = "NEWS"
    USER = "USER"
    DATA = "DATA"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    INFO = "info"


CATEGORY_OF: dict[EventType, Category] = {
    EventType.PRICE_MOVE: Category.PRICE,
    EventType.GAP_UP: Category.PRICE,
    EventType.GAP_DOWN: Category.PRICE,
    EventType.NEW_HIGH: Category.PRICE,
    EventType.NEW_LOW: Category.PRICE,
    EventType.VOLUME_SPIKE: Category.VOLUME,
    EventType.VOLUME_DIVERGENCE: Category.VOLUME,
    EventType.MA_CROSSOVER: Category.TECHNICAL,
    EventType.BREAKOUT: Category.TECHNICAL,
    EventType.BREAKDOWN: Category.TECHNICAL,
    EventType.RSI_REGIME_CHANGE: Category.TECHNICAL,
    EventType.VOLATILITY_SPIKE: Category.TECHNICAL,
    EventType.NEWS_SPIKE: Category.NEWS,
    EventType.NEWS_SENTIMENT_SHIFT: Category.NEWS,
    EventType.USER_THRESHOLD: Category.USER,
    EventType.SINCE_VISIT_MOVE: Category.USER,
    EventType.DATA_QUALITY_WARNING: Category.DATA,
}


# ─────────────────────────────────────────────────────────────────────────────
# Inputs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class ScoredNews:
    headline: str
    sentiment: str = "neutral"
    sentiment_confidence: float = 0.5
    topic: str = "General"
    published_at: datetime | None = None
    source: str = ""
    url: str = ""

    @property
    def polarity(self) -> int:
        return {"positive": 1, "negative": -1}.get(self.sentiment, 0)


@dataclass
class Baseline:
    """What the user had already acknowledged, last time they reviewed."""

    last_seen_price: float | None = None
    last_seen_volume: float | None = None
    last_seen_score: float | None = None
    last_seen_band: str | None = None
    last_seen_technical: dict = field(default_factory=dict)
    last_seen_event_fingerprints: list[str] = field(default_factory=list)
    last_seen_news_count: int = 0
    last_seen_news_sentiment: str | None = None
    last_reviewed_at: datetime | None = None

    @property
    def exists(self) -> bool:
        return self.last_seen_price is not None


@dataclass
class DataQuality:
    freshness: str = "FRESH"
    age_seconds: float | None = None
    source: str = "unknown"
    is_delayed: bool = False
    verification: str = "single_source"
    has_conflict: bool = False
    conflict_note: str | None = None
    is_demo: bool = False


@dataclass
class SignalInput:
    symbol: str
    name: str = ""
    currency: str = "USD"
    price: float | None = None
    previous_close: float | None = None
    change_percent: float | None = None
    open_price: float | None = None
    volume: float | None = None
    avg_volume: float | None = None
    technical: TechnicalState = field(default_factory=TechnicalState)
    news: list[ScoredNews] = field(default_factory=list)
    baseline: Baseline = field(default_factory=Baseline)
    data_quality: DataQuality = field(default_factory=DataQuality)
    user_threshold_percent: float | None = None
    now: datetime | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Outputs
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class DetectedEvent:
    type: EventType
    category: Category
    severity: Severity
    direction: str            # up | down | neutral
    title: str
    description: str
    metrics: dict = field(default_factory=dict)
    confidence: float = 0.7
    fingerprint: str = ""
    timestamp: datetime | None = None

    def to_dict(self) -> dict:
        from app.timeutil import to_iso

        return {
            "type": self.type.value,
            "category": self.category.value,
            "severity": self.severity.value,
            "direction": self.direction,
            "title": self.title,
            "description": self.description,
            "metrics": self.metrics,
            "confidence": round(self.confidence, 2),
            "fingerprint": self.fingerprint,
            "timestamp": to_iso(self.timestamp),
        }


@dataclass
class ScoreComponent:
    """One weighted contribution to the attention score, fully self-describing."""

    key: str
    label: str
    points: float
    max_points: float
    intensity: float          # 0–1, before weighting
    detail: str               # the human-readable "why"
    inputs: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "points": round(self.points, 1),
            "max_points": round(self.max_points, 1),
            "intensity": round(self.intensity, 3),
            "detail": self.detail,
            "inputs": self.inputs,
        }


@dataclass
class SinceLastVisit:
    has_baseline: bool = False
    price_change_percent: float | None = None
    price_from: float | None = None
    price_to: float | None = None
    volume_ratio_change: float | None = None
    score_from: float | None = None
    score_to: float | None = None
    score_delta: float | None = None
    band_from: str | None = None
    band_to: str | None = None
    new_signals: list[str] = field(default_factory=list)
    resolved_signals: list[str] = field(default_factory=list)
    persisting_signals: list[str] = field(default_factory=list)
    escalated: bool = False
    technical_changes: list[str] = field(default_factory=list)
    news_delta: int = 0
    last_reviewed_at: datetime | None = None
    is_meaningful: bool = False
    headline: str = ""

    def to_dict(self) -> dict:
        from app.timeutil import to_iso

        return {
            "has_baseline": self.has_baseline,
            "price_change_percent": _round(self.price_change_percent, 2),
            "price_from": _round(self.price_from, 2),
            "price_to": _round(self.price_to, 2),
            "volume_ratio_change": _round(self.volume_ratio_change, 2),
            "score_from": _round(self.score_from, 0),
            "score_to": _round(self.score_to, 0),
            "score_delta": _round(self.score_delta, 0),
            "band_from": self.band_from,
            "band_to": self.band_to,
            "new_signals": self.new_signals,
            "resolved_signals": self.resolved_signals,
            "persisting_signals": self.persisting_signals,
            "escalated": self.escalated,
            "technical_changes": self.technical_changes,
            "news_delta": self.news_delta,
            "last_reviewed_at": to_iso(self.last_reviewed_at),
            "is_meaningful": self.is_meaningful,
            "headline": self.headline,
        }


@dataclass
class SignalResult:
    symbol: str
    score: float
    band: str
    top_reason: str
    why_it_matters: str
    confidence: float
    components: list[ScoreComponent] = field(default_factory=list)
    events: list[DetectedEvent] = field(default_factory=list)
    since_last_visit: SinceLastVisit = field(default_factory=SinceLastVisit)
    computed_at: datetime | None = None

    @property
    def fingerprints(self) -> list[str]:
        return [e.fingerprint for e in self.events if e.category is not Category.DATA]

    def explanation(self) -> dict:
        """The payload behind the "Why?" disclosure in the UI."""
        return {
            "score": round(self.score, 1),
            "band": self.band,
            "confidence": round(self.confidence, 2),
            "top_reason": self.top_reason,
            "why_it_matters": self.why_it_matters,
            "components": [c.to_dict() for c in self.components],
            "weights": settings.weights.as_dict(),
            "reasons": [c.detail for c in self.components if c.points > 0.05],
        }

    def to_dict(self) -> dict:
        from app.timeutil import to_iso

        return {
            "symbol": self.symbol,
            "score": round(self.score, 1),
            "band": self.band,
            "top_reason": self.top_reason,
            "why_it_matters": self.why_it_matters,
            "confidence": round(self.confidence, 2),
            "components": [c.to_dict() for c in self.components],
            "events": [e.to_dict() for e in self.events],
            "since_last_visit": self.since_last_visit.to_dict(),
            "computed_at": to_iso(self.computed_at),
        }


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _saturate(value: float, scale: float) -> float:
    """Map [0, ∞) → [0, 1) with diminishing returns.

    A linear ramp with a hard cap makes every large move look identical once it
    clips; this keeps ordering meaningful at the top of the range, so a 12%
    move still outranks an 8% move after both have saturated the linear part.

    `scale` is the value at which the component reaches ~63% of its weight.
    """
    if scale <= 0:
        return 0.0
    return 1.0 - math.exp(-max(0.0, value) / scale)


# Saturation constants, calibrated so that a stock exhibiting a textbook
# high-conviction move — a ~7% gain, ~2.4× volume, a breakout, a moving-average
# crossover and a positive news cluster — lands in the low 80s, while a stock
# doing genuinely nothing lands in single digits. Named rather than inlined so
# the calibration is legible and adjustable in one place.
_PRICE_ABS_SCALE = 3.5     # a 3.5% move ≈ 63% of the price weight
_PRICE_Z_SCALE = 1.5       # a 1.5-sigma move ≈ 63% of the relative weight
_VOLUME_SCALE = 1.0        # 2.0× average volume ≈ 63% of the volume weight
_VOLATILITY_SCALE = 0.7    # 1.7× normal volatility ≈ 63% of the volatility weight


def band_for(score: float) -> str:
    if score >= settings.threshold_high_attention:
        return "HIGH_ATTENTION"
    if score >= settings.threshold_watch:
        return "WATCH"
    return "STABLE"


def _severity_for(intensity: float) -> Severity:
    if intensity >= 0.75:
        return Severity.CRITICAL
    if intensity >= 0.5:
        return Severity.HIGH
    if intensity >= 0.25:
        return Severity.MEDIUM
    return Severity.INFO


def _fmt_pct(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:+.{digits}f}%"


def _fmt_multiple(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}×"


# ─────────────────────────────────────────────────────────────────────────────
# The engine
# ─────────────────────────────────────────────────────────────────────────────


class SignalEngine:
    """Detects events and scores attention. Stateless and deterministic."""

    def __init__(self, weights: AttentionWeights | None = None):
        self.weights = weights or settings.weights

    # ── Public entry point ─────────────────────────────────────────────────
    def evaluate(self, data: SignalInput) -> SignalResult:
        now = data.now or utcnow()
        events: list[DetectedEvent] = []
        components: list[ScoreComponent] = []

        events += self._detect_price_events(data, now)
        events += self._detect_volume_events(data, now)
        events += self._detect_technical_events(data, now)
        events += self._detect_news_events(data, now)
        events += self._detect_user_events(data, now)
        events += self._detect_data_quality_events(data, now)

        components.append(self._score_price(data))
        components.append(self._score_volume(data))
        components.append(self._score_technical(data, events))
        components.append(self._score_news(data))
        components.append(self._score_volatility(data))
        components.append(self._score_recency(data, events))

        raw_score = sum(c.points for c in components)
        score = round(max(0.0, min(100.0, raw_score)), 1)

        since = self._diff_against_baseline(data, events, score)
        confidence = self._confidence(data, components, events)

        ranked = sorted(components, key=lambda c: c.points, reverse=True)
        top_reason = self._top_reason(events, ranked)

        return SignalResult(
            symbol=data.symbol,
            score=score,
            band=band_for(score),
            top_reason=top_reason,
            why_it_matters=self._why_it_matters(data, events, ranked, score),
            confidence=confidence,
            components=components,
            events=sorted(events, key=lambda e: (-_SEVERITY_RANK[e.severity], e.type.value)),
            since_last_visit=since,
            computed_at=now,
        )

    # ── Detection: price ───────────────────────────────────────────────────
    def _detect_price_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        out: list[DetectedEvent] = []
        chg = d.change_percent
        z = d.technical.move_zscore

        if chg is not None and abs(chg) >= settings.price_move_notable_percent:
            direction = "up" if chg > 0 else "down"
            intensity = max(_saturate(abs(chg), 4.0), _saturate(abs(z or 0), 2.0))
            relative = (
                f" — about {abs(z):.1f}× its typical daily range" if z and abs(z) >= 1.5 else ""
            )
            out.append(
                DetectedEvent(
                    type=EventType.PRICE_MOVE,
                    category=Category.PRICE,
                    severity=_severity_for(intensity),
                    direction=direction,
                    title=f"Price moved {_fmt_pct(chg)}",
                    description=f"{d.symbol} moved {_fmt_pct(chg)} versus the previous close{relative}.",
                    metrics={"change_percent": round(chg, 2), "zscore": _round(z, 2)},
                    confidence=0.95,
                    fingerprint=f"PRICE_MOVE:{direction}",
                    timestamp=now,
                )
            )

        # Gaps: measured open-vs-previous-close, which is a different event from
        # the day's total move and often the more informative one.
        if d.open_price and d.previous_close:
            gap = (d.open_price - d.previous_close) / d.previous_close * 100.0
            if abs(gap) >= 1.5:
                is_up = gap > 0
                intensity = _saturate(abs(gap), 3.0)
                out.append(
                    DetectedEvent(
                        type=EventType.GAP_UP if is_up else EventType.GAP_DOWN,
                        category=Category.PRICE,
                        severity=_severity_for(intensity),
                        direction="up" if is_up else "down",
                        title=f"Gapped {'up' if is_up else 'down'} {abs(gap):.2f}% at the open",
                        description=(
                            f"Opened at {d.open_price:,.2f} against a previous close of "
                            f"{d.previous_close:,.2f} — the move happened before the session began."
                        ),
                        metrics={"gap_percent": round(gap, 2)},
                        confidence=0.9,
                        fingerprint=f"GAP:{'up' if is_up else 'down'}",
                        timestamp=now,
                    )
                )

        # 52-week extremes, compared against the *prior* range so today's own
        # print cannot trivially set the record it is being measured against.
        t = d.technical
        if d.price and t.week52_high and d.price > t.week52_high:
            out.append(
                DetectedEvent(
                    type=EventType.NEW_HIGH,
                    category=Category.PRICE,
                    severity=Severity.HIGH,
                    direction="up",
                    title="New 52-week high",
                    description=(
                        f"Trading at {d.price:,.2f}, above the previous 52-week high of "
                        f"{t.week52_high:,.2f}."
                    ),
                    metrics={"price": d.price, "previous_52w_high": round(t.week52_high, 2)},
                    confidence=0.9,
                    fingerprint="NEW_HIGH",
                    timestamp=now,
                )
            )
        elif d.price and t.week52_low and d.price < t.week52_low:
            out.append(
                DetectedEvent(
                    type=EventType.NEW_LOW,
                    category=Category.PRICE,
                    severity=Severity.HIGH,
                    direction="down",
                    title="New 52-week low",
                    description=(
                        f"Trading at {d.price:,.2f}, below the previous 52-week low of "
                        f"{t.week52_low:,.2f}."
                    ),
                    metrics={"price": d.price, "previous_52w_low": round(t.week52_low, 2)},
                    confidence=0.9,
                    fingerprint="NEW_LOW",
                    timestamp=now,
                )
            )
        return out

    # ── Detection: volume ──────────────────────────────────────────────────
    def _detect_volume_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        ratio = d.technical.volume_ratio20
        if ratio is None:
            return []
        out: list[DetectedEvent] = []

        if ratio >= settings.volume_spike_ratio:
            intensity = _saturate(ratio - 1.0, 1.4)
            out.append(
                DetectedEvent(
                    type=EventType.VOLUME_SPIKE,
                    category=Category.VOLUME,
                    severity=_severity_for(intensity),
                    direction="neutral",
                    title=f"Volume {ratio:.1f}× its 20-day average",
                    description=(
                        f"{d.symbol} has traded {ratio:.2f}× its normal volume. Elevated volume "
                        "means more participants are acting on something, which makes an "
                        "accompanying price move more likely to persist."
                    ),
                    metrics={"volume_ratio": round(ratio, 2), "volume": d.volume,
                             "avg_volume": d.avg_volume},
                    confidence=0.9,
                    fingerprint="VOLUME_SPIKE",
                    timestamp=now,
                )
            )

            # Heavy volume with no price response is its own, distinct signal:
            # accumulation or distribution that has not yet moved the price.
            if d.change_percent is not None and abs(d.change_percent) < 1.0:
                out.append(
                    DetectedEvent(
                        type=EventType.VOLUME_DIVERGENCE,
                        category=Category.VOLUME,
                        severity=Severity.MEDIUM,
                        direction="neutral",
                        title="Heavy volume without a price move",
                        description=(
                            f"Volume is {ratio:.2f}× normal while the price has moved only "
                            f"{_fmt_pct(d.change_percent)}. Large two-way interest that has not "
                            "yet resolved into a direction."
                        ),
                        metrics={"volume_ratio": round(ratio, 2),
                                 "change_percent": round(d.change_percent, 2)},
                        confidence=0.7,
                        fingerprint="VOLUME_DIVERGENCE",
                        timestamp=now,
                    )
                )
        return out

    # ── Detection: technical ───────────────────────────────────────────────
    def _detect_technical_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        out: list[DetectedEvent] = []
        t = d.technical
        price = d.price
        if price is None:
            return out

        # Moving-average crossovers. We require yesterday to have been on the
        # other side, so this fires on the *transition*, not on the state.
        for period, sma_now, sma_prev in (
            (20, t.sma20, t.prev_sma20),
            (50, t.sma50, t.prev_sma50),
        ):
            if sma_now is None or sma_prev is None or t.prev_close is None:
                continue
            was_above = t.prev_close > sma_prev
            is_above = price > sma_now
            if was_above == is_above:
                continue
            direction = "up" if is_above else "down"
            out.append(
                DetectedEvent(
                    type=EventType.MA_CROSSOVER,
                    category=Category.TECHNICAL,
                    severity=Severity.HIGH if period == 50 else Severity.MEDIUM,
                    direction=direction,
                    title=f"Crossed {'above' if is_above else 'below'} the {period}-day average",
                    description=(
                        f"Price moved from {'above' if was_above else 'below'} to "
                        f"{'above' if is_above else 'below'} its {period}-day moving average "
                        f"({sma_now:,.2f}) — a change in trend regime, not just a daily move."
                    ),
                    metrics={"period": period, "sma": round(sma_now, 2), "price": price},
                    confidence=0.8,
                    fingerprint=f"MA_CROSSOVER:{period}:{direction}",
                    timestamp=now,
                )
            )

        # Breakout / breakdown, with a small margin so ordinary noise brushing
        # the level does not register as a regime change.
        margin = 1.002
        if t.resistance60 and price > t.resistance60 * margin:
            out.append(
                DetectedEvent(
                    type=EventType.BREAKOUT,
                    category=Category.TECHNICAL,
                    severity=Severity.HIGH,
                    direction="up",
                    title="Broke above 60-day resistance",
                    description=(
                        f"Price cleared {t.resistance60:,.2f}, the highest close of the past 60 "
                        "sessions — the level that had been capping every prior attempt."
                    ),
                    metrics={"resistance": round(t.resistance60, 2), "price": price},
                    confidence=0.75,
                    fingerprint="BREAKOUT",
                    timestamp=now,
                )
            )
        elif t.support60 and price < t.support60 / margin:
            out.append(
                DetectedEvent(
                    type=EventType.BREAKDOWN,
                    category=Category.TECHNICAL,
                    severity=Severity.HIGH,
                    direction="down",
                    title="Broke below 60-day support",
                    description=(
                        f"Price fell through {t.support60:,.2f}, the lowest close of the past 60 "
                        "sessions — the level that had been holding on every prior test."
                    ),
                    metrics={"support": round(t.support60, 2), "price": price},
                    confidence=0.75,
                    fingerprint="BREAKDOWN",
                    timestamp=now,
                )
            )

        # RSI regime — reported only on a *change* of zone, per the brief's
        # instruction not to bury the user in indicators.
        zone = t.rsi_zone
        previous_zone = (d.baseline.last_seen_technical or {}).get("rsi_zone")
        if zone in ("overbought", "oversold") and previous_zone not in (None, zone):
            out.append(
                DetectedEvent(
                    type=EventType.RSI_REGIME_CHANGE,
                    category=Category.TECHNICAL,
                    severity=Severity.MEDIUM,
                    direction="up" if zone == "overbought" else "down",
                    title=f"RSI entered {zone} territory",
                    description=(
                        f"14-day RSI is {t.rsi14:.0f}, moving from {previous_zone} to {zone} "
                        "since you last reviewed this stock."
                    ),
                    metrics={"rsi": _round(t.rsi14, 1), "zone": zone, "previous_zone": previous_zone},
                    confidence=0.65,
                    fingerprint=f"RSI:{zone}",
                    timestamp=now,
                )
            )

        vol_ratio = t.volatility_ratio
        if vol_ratio and vol_ratio >= settings.volatility_spike_ratio:
            intensity = _saturate(vol_ratio - 1.0, 1.0)
            out.append(
                DetectedEvent(
                    type=EventType.VOLATILITY_SPIKE,
                    category=Category.TECHNICAL,
                    severity=_severity_for(intensity),
                    direction="neutral",
                    title=f"Volatility {vol_ratio:.1f}× its usual level",
                    description=(
                        f"20-day realised volatility is {t.volatility20:.1f}% against a longer-run "
                        f"{t.volatility_baseline:.1f}%. The stock has entered a wider trading "
                        "regime, so its recent price levels are less reliable as reference points."
                    ),
                    metrics={"volatility": _round(t.volatility20, 2),
                             "baseline": _round(t.volatility_baseline, 2),
                             "ratio": round(vol_ratio, 2)},
                    confidence=0.7,
                    fingerprint="VOLATILITY_SPIKE",
                    timestamp=now,
                )
            )
        return out

    # ── Detection: news ────────────────────────────────────────────────────
    def _detect_news_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        if not d.news:
            return []
        out: list[DetectedEvent] = []
        recent = [n for n in d.news if _within_hours(n.published_at, 48, now)]
        count = len(recent)
        if count == 0:
            return []

        polarity = sum(n.polarity * n.sentiment_confidence for n in recent)
        net = polarity / count
        if net > 0.25:
            tone, tone_word = "positive", "positive"
        elif net < -0.25:
            tone, tone_word = "negative", "negative"
        else:
            tone, tone_word = "mixed", "mixed"

        topics = _dominant_topics(recent)
        topic_phrase = f" clustered around {topics[0]}" if topics else ""

        if count >= settings.news_spike_count:
            intensity = _clamp01(count / 5.0)
            out.append(
                DetectedEvent(
                    type=EventType.NEWS_SPIKE,
                    category=Category.NEWS,
                    severity=_severity_for(max(intensity, abs(net))),
                    direction={"positive": "up", "negative": "down"}.get(tone, "neutral"),
                    title=f"{count} related stories in the last 48 hours",
                    description=(
                        f"News flow is elevated{topic_phrase}, with {tone_word} tone overall. "
                        "Clustered coverage usually means a single underlying catalyst."
                    ),
                    metrics={"count": count, "tone": tone, "net_sentiment": round(net, 2),
                             "topics": topics},
                    confidence=0.7,
                    fingerprint="NEWS_SPIKE",
                    timestamp=now,
                )
            )
        elif count:
            out.append(
                DetectedEvent(
                    type=EventType.NEWS_SPIKE,
                    category=Category.NEWS,
                    severity=Severity.INFO,
                    direction={"positive": "up", "negative": "down"}.get(tone, "neutral"),
                    title=f"{count} recent {'story' if count == 1 else 'stories'}",
                    description=f"Coverage{topic_phrase} with {tone_word} tone.",
                    metrics={"count": count, "tone": tone, "net_sentiment": round(net, 2),
                             "topics": topics},
                    confidence=0.55,
                    fingerprint="NEWS_PRESENT",
                    timestamp=now,
                )
            )

        # A change in tone since the user last looked is more actionable than
        # the tone itself.
        previous_tone = d.baseline.last_seen_news_sentiment
        if previous_tone and tone != previous_tone and tone != "mixed":
            out.append(
                DetectedEvent(
                    type=EventType.NEWS_SENTIMENT_SHIFT,
                    category=Category.NEWS,
                    severity=Severity.MEDIUM,
                    direction={"positive": "up", "negative": "down"}.get(tone, "neutral"),
                    title=f"Coverage turned {tone}",
                    description=(
                        f"Tone moved from {previous_tone} to {tone} since your last review."
                    ),
                    metrics={"from": previous_tone, "to": tone},
                    confidence=0.6,
                    fingerprint=f"NEWS_SHIFT:{tone}",
                    timestamp=now,
                )
            )
        return out

    # ── Detection: user relevance ──────────────────────────────────────────
    def _detect_user_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        out: list[DetectedEvent] = []
        b = d.baseline

        if b.exists and d.price and b.last_seen_price:
            delta = (d.price - b.last_seen_price) / b.last_seen_price * 100.0
            if abs(delta) >= settings.since_visit_notable_percent:
                direction = "up" if delta > 0 else "down"
                intensity = _saturate(abs(delta), 4.0)
                out.append(
                    DetectedEvent(
                        type=EventType.SINCE_VISIT_MOVE,
                        category=Category.USER,
                        severity=_severity_for(intensity),
                        direction=direction,
                        title=f"{_fmt_pct(delta)} since you last checked",
                        description=(
                            f"You last reviewed {d.symbol} at {b.last_seen_price:,.2f}; it is now "
                            f"{d.price:,.2f}."
                        ),
                        metrics={"change_percent": round(delta, 2),
                                 "from": round(b.last_seen_price, 2), "to": round(d.price, 2)},
                        confidence=0.95,
                        fingerprint="SINCE_VISIT_MOVE",
                        timestamp=now,
                    )
                )

        threshold = d.user_threshold_percent
        if threshold and d.change_percent is not None and abs(d.change_percent) >= abs(threshold):
            out.append(
                DetectedEvent(
                    type=EventType.USER_THRESHOLD,
                    category=Category.USER,
                    severity=Severity.HIGH,
                    direction="up" if d.change_percent > 0 else "down",
                    title=f"Your {abs(threshold):.1f}% alert triggered",
                    description=(
                        f"You asked to be told when {d.symbol} moved more than "
                        f"{abs(threshold):.1f}%. It has moved {_fmt_pct(d.change_percent)}."
                    ),
                    metrics={"threshold": threshold, "change_percent": round(d.change_percent, 2)},
                    confidence=1.0,
                    fingerprint="USER_THRESHOLD",
                    timestamp=now,
                )
            )
        return out

    # ── Detection: data quality ────────────────────────────────────────────
    def _detect_data_quality_events(self, d: SignalInput, now: datetime) -> list[DetectedEvent]:
        """Data problems are events too — they just don't earn attention points.

        Telling the user "this looks quiet" when in truth we could not reach the
        provider is the one failure mode this product cannot afford.
        """
        out: list[DetectedEvent] = []
        q = d.data_quality

        if q.freshness in ("STALE", "UNAVAILABLE"):
            minutes = int((q.age_seconds or 0) // 60)
            out.append(
                DetectedEvent(
                    type=EventType.DATA_QUALITY_WARNING,
                    category=Category.DATA,
                    severity=Severity.MEDIUM,
                    direction="neutral",
                    title="Delayed data",
                    description=(
                        f"The most recent quote from {q.source} is {minutes} minutes old. "
                        "Signals below are computed from that snapshot."
                    ),
                    metrics={"freshness": q.freshness, "age_seconds": _round(q.age_seconds, 0)},
                    confidence=1.0,
                    fingerprint="DATA_STALE",
                    timestamp=now,
                )
            )

        if q.has_conflict:
            out.append(
                DetectedEvent(
                    type=EventType.DATA_QUALITY_WARNING,
                    category=Category.DATA,
                    severity=Severity.MEDIUM,
                    direction="neutral",
                    title="Data discrepancy detected",
                    description=q.conflict_note or "Two sources disagree on the current price.",
                    metrics={"verification": q.verification},
                    confidence=1.0,
                    fingerprint="DATA_CONFLICT",
                    timestamp=now,
                )
            )
        return out

    # ── Scoring ────────────────────────────────────────────────────────────
    def _score_price(self, d: SignalInput) -> ScoreComponent:
        cap = self.weights.price_move
        chg, z = d.change_percent, d.technical.move_zscore

        if chg is None:
            return ScoreComponent("price_move", "Price movement", 0.0, cap, 0.0,
                                  "No price change available", {})

        absolute = _saturate(abs(chg), _PRICE_ABS_SCALE)
        relative = _saturate(abs(z), _PRICE_Z_SCALE) if z is not None else absolute

        # Weighting both halves is the point: the absolute move is what the user
        # sees, the relative move is what makes it unusual *for this stock*.
        intensity = 0.45 * absolute + 0.55 * relative
        points = cap * intensity

        if z is not None and abs(z) >= 1.5:
            detail = (
                f"Price moved {_fmt_pct(chg)}, roughly {abs(z):.1f}× this stock's typical "
                "daily range"
            )
        else:
            detail = f"Price moved {_fmt_pct(chg)}"

        return ScoreComponent(
            "price_move", "Price movement", points, cap, intensity, detail,
            {"change_percent": round(chg, 2), "zscore": _round(z, 2),
             "absolute_intensity": round(absolute, 3), "relative_intensity": round(relative, 3)},
        )

    def _score_volume(self, d: SignalInput) -> ScoreComponent:
        cap = self.weights.volume_anomaly
        ratio = d.technical.volume_ratio20
        if ratio is None:
            return ScoreComponent("volume_anomaly", "Volume anomaly", 0.0, cap, 0.0,
                                  "No volume data available", {})

        # Only volume *above* normal is interesting; a quiet day is not a signal.
        intensity = _saturate(max(0.0, ratio - 1.0), _VOLUME_SCALE)
        points = cap * intensity
        detail = (
            f"Volume is {ratio:.2f}× its 20-day average"
            if ratio >= 1.15
            else f"Volume is normal ({ratio:.2f}× average)"
        )
        return ScoreComponent(
            "volume_anomaly", "Volume anomaly", points, cap, intensity, detail,
            {"volume_ratio": round(ratio, 2), "volume": d.volume, "avg_volume": d.avg_volume},
        )

    def _score_technical(self, d: SignalInput, events: list[DetectedEvent]) -> ScoreComponent:
        cap = self.weights.technical
        # Discrete regime changes, each worth a fixed share. Summed then capped,
        # so a stock that breaks out *and* crosses its 50-day scores higher than
        # one that only does the former, without any single event dominating.
        contributions = {
            EventType.BREAKOUT: 0.55,
            EventType.BREAKDOWN: 0.55,
            EventType.MA_CROSSOVER: 0.45,
            EventType.NEW_HIGH: 0.5,
            EventType.NEW_LOW: 0.5,
            EventType.RSI_REGIME_CHANGE: 0.25,
        }
        matched = [e for e in events if e.type in contributions]
        intensity = _clamp01(sum(contributions[e.type] for e in matched))
        points = cap * intensity

        if matched:
            detail = "; ".join(e.title for e in matched[:3])
        else:
            detail = "No technical regime change"
        return ScoreComponent(
            "technical", "Technical regime change", points, cap, intensity, detail,
            {"events": [e.type.value for e in matched],
             "rsi": _round(d.technical.rsi14, 1),
             "sma20": _round(d.technical.sma20, 2),
             "sma50": _round(d.technical.sma50, 2)},
        )

    def _score_news(self, d: SignalInput) -> ScoreComponent:
        cap = self.weights.news
        now = d.now or utcnow()
        recent = [n for n in d.news if _within_hours(n.published_at, 48, now)]
        if not recent:
            return ScoreComponent("news", "News & events", 0.0, cap, 0.0,
                                  "No recent news detected", {"count": 0})

        count = len(recent)
        volume_component = _clamp01(count / 4.0)

        # Directional, confident coverage matters more than a neutral drip feed.
        polarity = sum(n.polarity * n.sentiment_confidence for n in recent) / count
        conviction = _clamp01(abs(polarity))

        # Freshness: a story from 40 hours ago is mostly priced in already.
        newest = min(
            (age_seconds(n.published_at, now=now) or 1e9 for n in recent), default=1e9
        )
        recency = _clamp01(1.0 - (newest / (48 * 3600)))

        intensity = _clamp01(0.45 * volume_component + 0.35 * conviction + 0.20 * recency)
        points = cap * intensity

        tone = "positive" if polarity > 0.25 else "negative" if polarity < -0.25 else "mixed"
        topics = _dominant_topics(recent)
        topic_phrase = f" on {topics[0]}" if topics else ""
        detail = (
            f"{count} related news {'item' if count == 1 else 'items'}{topic_phrase} "
            f"with {tone} tone"
        )
        return ScoreComponent(
            "news", "News & events", points, cap, intensity, detail,
            {"count": count, "tone": tone, "net_sentiment": round(polarity, 2),
             "topics": topics, "newest_age_seconds": int(min(newest, 1e9))},
        )

    def _score_volatility(self, d: SignalInput) -> ScoreComponent:
        cap = self.weights.volatility
        t = d.technical
        ratio = t.volatility_ratio
        if ratio is None:
            return ScoreComponent("volatility", "Volatility anomaly", 0.0, cap, 0.0,
                                  "Insufficient history for a volatility baseline", {})
        intensity = _saturate(max(0.0, ratio - 1.0), _VOLATILITY_SCALE)
        points = cap * intensity
        if ratio >= 1.25:
            detail = (
                f"Volatility is {ratio:.2f}× its longer-run level "
                f"({t.volatility20:.1f}% vs {t.volatility_baseline:.1f}%)"
            )
        else:
            detail = f"Volatility is normal ({ratio:.2f}× baseline)"
        return ScoreComponent(
            "volatility", "Volatility anomaly", points, cap, intensity, detail,
            {"volatility_20d": _round(t.volatility20, 2),
             "baseline": _round(t.volatility_baseline, 2), "ratio": round(ratio, 2)},
        )

    def _score_recency(self, d: SignalInput, events: list[DetectedEvent]) -> ScoreComponent:
        """Points for what changed *for this user*, since *their* last review.

        This is the component that makes two users with identical watchlists see
        different attention scores, and it is the reason the product is not just
        a screener.
        """
        cap = self.weights.recency
        b = d.baseline
        if not b.exists:
            # Never reviewed: the whole stock is new information, but we do not
            # want a fresh watchlist to light up entirely red.
            return ScoreComponent(
                "recency", "Change since your last visit", cap * 0.3, cap, 0.3,
                "First look — no prior baseline to compare against",
                {"has_baseline": False},
            )

        parts: list[str] = []
        intensity = 0.0

        if d.price and b.last_seen_price:
            delta = abs((d.price - b.last_seen_price) / b.last_seen_price * 100.0)
            move_component = _saturate(delta, 4.0)
            intensity += 0.6 * move_component
            if delta >= settings.since_visit_notable_percent:
                signed = (d.price - b.last_seen_price) / b.last_seen_price * 100.0
                parts.append(f"{_fmt_pct(signed)} since your last review")

        new_fingerprints = {
            e.fingerprint for e in events if e.category is not Category.DATA
        } - set(b.last_seen_event_fingerprints or [])
        if new_fingerprints:
            intensity += 0.4 * _clamp01(len(new_fingerprints) / 3.0)
            parts.append(
                f"{len(new_fingerprints)} new signal{'s' if len(new_fingerprints) != 1 else ''}"
            )

        intensity = _clamp01(intensity)
        points = cap * intensity
        detail = "; ".join(parts) if parts else "Nothing new since your last review"
        return ScoreComponent(
            "recency", "Change since your last visit", points, cap, intensity, detail,
            {"has_baseline": True, "new_signals": sorted(new_fingerprints),
             "last_reviewed_at": b.last_reviewed_at.isoformat() if b.last_reviewed_at else None},
        )

    # ── Baseline diff ──────────────────────────────────────────────────────
    def _diff_against_baseline(
        self, d: SignalInput, events: list[DetectedEvent], score: float
    ) -> SinceLastVisit:
        b = d.baseline
        band = band_for(score)
        since = SinceLastVisit(
            has_baseline=b.exists,
            price_to=d.price,
            score_to=score,
            band_to=band,
            last_reviewed_at=b.last_reviewed_at,
        )
        if not b.exists:
            since.headline = "Not yet reviewed"
            since.is_meaningful = True
            return since

        since.price_from = b.last_seen_price
        since.score_from = b.last_seen_score
        since.band_from = b.last_seen_band

        if d.price and b.last_seen_price:
            since.price_change_percent = (d.price - b.last_seen_price) / b.last_seen_price * 100.0
        if b.last_seen_score is not None:
            since.score_delta = score - b.last_seen_score
        if d.volume and b.last_seen_volume:
            since.volume_ratio_change = d.volume / b.last_seen_volume

        current = {e.fingerprint for e in events if e.category is not Category.DATA}
        previous = set(b.last_seen_event_fingerprints or [])
        since.new_signals = sorted(current - previous)
        since.resolved_signals = sorted(previous - current)
        since.persisting_signals = sorted(current & previous)
        since.escalated = bool(
            b.last_seen_band and band != b.last_seen_band
            and _BAND_RANK[band] > _BAND_RANK.get(b.last_seen_band, 0)
        )

        # Technical regime differences, described in plain language.
        prev_tech = b.last_seen_technical or {}
        now_tech = d.technical.regime(d.price)
        labels = {
            "above_sma20": "20-day average",
            "above_sma50": "50-day average",
            "above_resistance": "60-day resistance",
            "below_support": "60-day support",
        }
        for key, label in labels.items():
            was, is_now = prev_tech.get(key), now_tech.get(key)
            if was is None or is_now is None or was == is_now:
                continue
            if key == "below_support":
                since.technical_changes.append(
                    f"Now {'below' if is_now else 'back above'} {label}"
                )
            else:
                since.technical_changes.append(
                    f"Now {'above' if is_now else 'below'} {label}"
                )
        if prev_tech.get("rsi_zone") and prev_tech["rsi_zone"] != now_tech["rsi_zone"]:
            since.technical_changes.append(
                f"RSI {prev_tech['rsi_zone']} → {now_tech['rsi_zone']}"
            )

        news_now = len([n for n in d.news if _within_hours(n.published_at, 48, d.now or utcnow())])
        since.news_delta = news_now - (b.last_seen_news_count or 0)

        since.is_meaningful = _is_meaningful(since, score)
        since.headline = _since_headline(since, d)
        return since

    # ── Confidence ─────────────────────────────────────────────────────────
    def _confidence(
        self, d: SignalInput, components: list[ScoreComponent], events: list[DetectedEvent]
    ) -> float:
        """How much to trust this score.

        Confidence is about the *evidence*, not the size of the move. A 7% move
        on stale data from a single unverified source deserves less trust than a
        3% move confirmed by volume across two agreeing sources.
        """
        confidence = 0.6
        q = d.data_quality

        confidence += {"FRESH": 0.2, "RECENT": 0.1, "STALE": -0.2, "UNAVAILABLE": -0.35}.get(
            q.freshness, 0.0
        )
        if q.verification == "verified":
            confidence += 0.12
        elif q.verification == "conflict":
            confidence -= 0.25

        # Corroboration across independent signal families is the strongest
        # evidence we have that something real is happening.
        families = {
            e.category for e in events
            if e.category in (Category.PRICE, Category.VOLUME, Category.TECHNICAL, Category.NEWS)
        }
        confidence += 0.06 * max(0, len(families) - 1)

        if d.technical.sma50 is None:
            confidence -= 0.1  # thin history
        return round(_clamp01(confidence), 2)

    # ── Narrative ──────────────────────────────────────────────────────────
    def _top_reason(self, events: list[DetectedEvent], ranked: list[ScoreComponent]) -> str:
        """The single phrase shown in the attention queue row."""
        priority = [
            (EventType.NEW_HIGH, "52-week high"),
            (EventType.NEW_LOW, "52-week low"),
            (EventType.BREAKOUT, "Breakout"),
            (EventType.BREAKDOWN, "Breakdown"),
            (EventType.USER_THRESHOLD, "Your alert triggered"),
            (EventType.VOLUME_DIVERGENCE, "Volume divergence"),
            (EventType.MA_CROSSOVER, "Trend change"),
            (EventType.VOLUME_SPIKE, "Volume spike"),
            (EventType.VOLATILITY_SPIKE, "Volatility expansion"),
            (EventType.NEWS_SPIKE, "News activity"),
            (EventType.GAP_UP, "Gap up"),
            (EventType.GAP_DOWN, "Gap down"),
            (EventType.PRICE_MOVE, "Large move"),
        ]
        present = {e.type for e in events}
        # Prefer the most *specific* explanation available, not merely the
        # highest-scoring one: "Breakout" tells the user more than "Large move"
        # even when the price component contributed more points.
        for event_type, label in priority:
            if event_type in present:
                return label
        # No named event fired. Only fall back to a component label if that
        # component is actually pulling weight — a few points out of its
        # maximum is noise, not a headline.
        if ranked and ranked[0].points >= 0.35 * ranked[0].max_points:
            return ranked[0].label
        return "No meaningful change"

    def _why_it_matters(
        self, d: SignalInput, events: list[DetectedEvent],
        ranked: list[ScoreComponent], score: float,
    ) -> str:
        """A written explanation combining the signals, not just listing them.

        The combinations carry the real insight: price plus volume is
        confirmation, price without volume is suspect, and volume without price
        is a coiled spring. A list of bullet points cannot say that.
        """
        by_key = {c.key: c for c in ranked}
        price_c = by_key.get("price_move")
        volume_c = by_key.get("volume_anomaly")
        news_c = by_key.get("news")

        chg = d.change_percent
        ratio = d.technical.volume_ratio20
        types = {e.type for e in events}

        strong_price = bool(price_c and price_c.intensity >= 0.45)
        strong_volume = bool(ratio and ratio >= settings.volume_spike_ratio)
        has_news = bool(news_c and news_c.intensity >= 0.3)
        direction = "higher" if (chg or 0) > 0 else "lower"

        sentences: list[str] = []

        if strong_price and strong_volume:
            sentences.append(
                f"{d.symbol} moved {_fmt_pct(chg)} {direction} while trading at "
                f"{ratio:.1f}× its normal volume — a large move confirmed by unusually "
                "heavy participation."
            )
        elif strong_price and ratio and ratio < 1.1:
            sentences.append(
                f"{d.symbol} moved {_fmt_pct(chg)} but volume is only {ratio:.1f}× normal. "
                "A move on light volume is less well supported and more prone to reversing."
            )
        elif strong_volume and not strong_price:
            sentences.append(
                f"{d.symbol} is trading at {ratio:.1f}× its normal volume without a matching "
                f"price move ({_fmt_pct(chg)}). Heavy two-way interest that has not yet "
                "resolved into a direction."
            )
        elif strong_price:
            sentences.append(f"{d.symbol} moved {_fmt_pct(chg)} {direction}.")

        if EventType.BREAKOUT in types:
            sentences.append(
                "The move carried price above the level that had capped the last 60 sessions."
            )
        elif EventType.BREAKDOWN in types:
            sentences.append(
                "Price broke through the floor that had held for the last 60 sessions."
            )
        if EventType.NEW_HIGH in types:
            sentences.append("It is now trading at a fresh 52-week high.")
        elif EventType.NEW_LOW in types:
            sentences.append("It is now trading at a fresh 52-week low.")

        ma_events = [e for e in events if e.type is EventType.MA_CROSSOVER]
        if ma_events:
            sentences.append(ma_events[0].description.split(" — ")[0].rstrip(".") + ".")

        if has_news:
            count = news_c.inputs.get("count", 0)
            tone = news_c.inputs.get("tone", "mixed")
            topics = news_c.inputs.get("topics") or []
            topic_phrase = f" concentrated on {topics[0]}" if topics else ""
            sentences.append(
                f"This coincides with {count} recent news "
                f"{'item' if count == 1 else 'items'}{topic_phrase}, with {tone} tone."
            )

        if EventType.VOLATILITY_SPIKE in types:
            sentences.append(
                "Volatility has expanded well beyond its usual range, so recent price levels "
                "are a weaker guide than normal."
            )

        if d.data_quality.has_conflict:
            sentences.append(
                "Note that two data sources currently disagree on the price, so treat the "
                "exact figures with caution."
            )
        elif d.data_quality.freshness in ("STALE", "UNAVAILABLE"):
            sentences.append(
                "This assessment is based on delayed data and may not reflect the current price."
            )

        if not sentences:
            return (
                f"Nothing meaningful has changed for {d.symbol}. Price, volume, technical state "
                "and news flow are all within their normal ranges."
            )
        return " ".join(sentences)


# ─────────────────────────────────────────────────────────────────────────────
# Module-level helpers
# ─────────────────────────────────────────────────────────────────────────────

_SEVERITY_RANK = {
    Severity.CRITICAL: 4, Severity.HIGH: 3, Severity.MEDIUM: 2, Severity.INFO: 1,
}
_BAND_RANK = {"STABLE": 0, "WATCH": 1, "HIGH_ATTENTION": 2}


def _within_hours(when: datetime | None, hours: float, now: datetime) -> bool:
    if when is None:
        return False
    age = age_seconds(when, now=now)
    return age is not None and age <= hours * 3600


def _dominant_topics(news: list[ScoredNews], limit: int = 2) -> list[str]:
    counts: dict[str, int] = {}
    for item in news:
        topic = (item.topic or "General").strip()
        if topic.lower() == "general":
            continue
        counts[topic] = counts.get(topic, 0) + 1
    return [t for t, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]]


def _is_meaningful(since: SinceLastVisit, score: float) -> bool:
    """The definition of "meaningful change" — deliberately in one place.

    A change earns a place in "Since your last visit" if *any* of these hold.
    They are ORed rather than summed because they are genuinely different kinds
    of relevance, and a stock that quietly crossed its 50-day average matters
    even though its price barely moved.
    """
    if since.price_change_percent is not None:
        if abs(since.price_change_percent) >= settings.since_visit_notable_percent:
            return True
    if since.new_signals:
        return True
    if since.escalated:
        return True
    if since.score_delta is not None and abs(since.score_delta) >= 15:
        return True
    if since.technical_changes:
        return True
    if since.news_delta >= settings.news_spike_count:
        return True
    return False


def _since_headline(since: SinceLastVisit, d: SignalInput) -> str:
    if not since.is_meaningful:
        return "No meaningful change"
    bits: list[str] = []
    if since.price_change_percent is not None and abs(since.price_change_percent) >= 0.5:
        bits.append(f"{_fmt_pct(since.price_change_percent)} since last check")
    if since.score_delta is not None and abs(since.score_delta) >= 5:
        bits.append(f"attention {since.score_delta:+.0f}")
    if since.new_signals:
        count = len(since.new_signals)
        bits.append(f"{count} new signal{'s' if count != 1 else ''}")
    if since.technical_changes:
        bits.append(since.technical_changes[0].lower())
    return " · ".join(bits[:3]) if bits else "Updated"


_engine: SignalEngine | None = None


def get_signal_engine() -> SignalEngine:
    global _engine
    if _engine is None:
        _engine = SignalEngine()
    return _engine
