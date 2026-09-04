"""Unit tests for the Meaningful Change Engine.

These are the tests that matter most: the engine is a pure function, so every
one of them is "this exact market state produces this exact score / this exact
event", with no HTTP, no database and no clock in the way.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.config import settings
from app.services.indicators import TechnicalState
from app.services.signal_engine import (
    Baseline,
    DataQuality,
    EventType,
    ScoredNews,
    SignalEngine,
    SignalInput,
    band_for,
)
from app.timeutil import utcnow


@pytest.fixture()
def engine() -> SignalEngine:
    return SignalEngine()


def _calm_technical(price: float = 100.0) -> TechnicalState:
    """A technical state in which nothing is happening."""
    return TechnicalState(
        sma20=99.0,
        sma50=98.0,
        rsi14=52.0,
        volatility20=20.0,
        volatility_baseline=20.0,
        volume_ratio20=1.0,
        resistance60=110.0,
        support60=90.0,
        move_zscore=0.2,
        week52_high=125.0,
        week52_low=80.0,
        prev_close=99.5,
        prev_sma20=99.0,
        prev_sma50=98.0,
    )


def _base_input(**overrides) -> SignalInput:
    defaults = dict(
        symbol="TEST",
        name="Test Corp",
        price=100.0,
        previous_close=99.5,
        change_percent=0.5,
        open_price=99.6,
        volume=1_000_000,
        avg_volume=1_000_000,
        technical=_calm_technical(),
        news=[],
        baseline=Baseline(),
        data_quality=DataQuality(freshness="FRESH", age_seconds=20, source="test", verification="verified"),
        now=utcnow(),
    )
    defaults.update(overrides)
    return SignalInput(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# Attention score
# ─────────────────────────────────────────────────────────────────────────────


def test_quiet_stock_scores_near_zero(engine):
    result = engine.evaluate(_base_input())
    assert result.score < 15
    assert result.band == "STABLE"
    assert result.top_reason == "No meaningful change"


def test_score_is_the_sum_of_its_components(engine):
    """The core transparency guarantee: total == sum of parts, clamped to 100."""
    result = engine.evaluate(
        _base_input(
            change_percent=6.8,
            technical=TechnicalState(
                sma20=96.0, sma50=95.0, prev_sma20=101.0, prev_sma50=101.0,
                rsi14=68.0, volatility20=40.0, volatility_baseline=22.0,
                volume_ratio20=2.4, resistance60=99.0, support60=88.0,
                move_zscore=2.1, week52_high=130.0, week52_low=70.0, prev_close=99.5,
            ),
        )
    )
    parts = sum(c.points for c in result.components)
    assert result.score == pytest.approx(min(100.0, round(parts, 1)), abs=0.11)
    assert len(result.components) == 6


def test_each_component_respects_its_configured_maximum(engine):
    """No component may ever exceed its weight, however extreme the input."""
    extreme = engine.evaluate(
        _base_input(
            change_percent=45.0,
            volume=50_000_000,
            avg_volume=1_000_000,
            technical=TechnicalState(
                sma20=50.0, sma50=40.0, prev_sma20=200.0, prev_sma50=200.0,
                rsi14=95.0, volatility20=200.0, volatility_baseline=10.0,
                volume_ratio20=50.0, resistance60=60.0, support60=30.0,
                move_zscore=25.0, week52_high=80.0, week52_low=20.0, prev_close=99.5,
            ),
        )
    )
    weights = settings.weights.as_dict()
    for component in extreme.components:
        assert component.points <= weights[component.key] + 1e-6
    assert extreme.score <= 100.0


def test_big_move_on_volume_reaches_high_attention(engine):
    result = engine.evaluate(
        _base_input(
            change_percent=6.8,
            volume=2_400_000,
            avg_volume=1_000_000,
            technical=TechnicalState(
                sma20=96.0, sma50=95.0, prev_sma20=100.5, prev_sma50=100.2,
                rsi14=66.0, volatility20=38.0, volatility_baseline=22.0,
                volume_ratio20=2.4, resistance60=98.5, support60=88.0,
                move_zscore=2.0, week52_high=130.0, week52_low=70.0, prev_close=99.5,
            ),
            news=[
                ScoredNews("Company wins major supply contract", "positive", 0.8, "Deals",
                           utcnow() - timedelta(minutes=30)),
                ScoredNews("Analysts raise targets on strong outlook", "positive", 0.75, "Analyst Actions",
                           utcnow() - timedelta(hours=1)),
                ScoredNews("Shipments beat prior guidance", "positive", 0.7, "Supply Chain",
                           utcnow() - timedelta(hours=2)),
            ],
            # A returning user who last reviewed this stock a few hours ago:
            # the change-since-visit component contributes too.
            baseline=Baseline(
                last_seen_price=93.5, last_seen_score=30.0, last_seen_band="STABLE",
                last_seen_event_fingerprints=[],
                last_reviewed_at=utcnow() - timedelta(hours=4),
            ),
        )
    )
    assert result.band == "HIGH_ATTENTION"
    assert result.score >= settings.threshold_high_attention


def test_relative_move_matters_not_just_absolute(engine):
    """A 3% move on a placid stock outscores 3% on a jumpy one."""
    placid = engine.evaluate(
        _base_input(change_percent=3.0, technical=_with(_calm_technical(), move_zscore=3.4))
    )
    jumpy = engine.evaluate(
        _base_input(change_percent=3.0, technical=_with(_calm_technical(), move_zscore=0.7))
    )
    price_placid = next(c for c in placid.components if c.key == "price_move")
    price_jumpy = next(c for c in jumpy.components if c.key == "price_move")
    assert price_placid.points > price_jumpy.points


def test_band_thresholds():
    assert band_for(80) == "HIGH_ATTENTION"
    assert band_for(settings.threshold_high_attention) == "HIGH_ATTENTION"
    assert band_for(50) == "WATCH"
    assert band_for(settings.threshold_watch) == "WATCH"
    assert band_for(10) == "STABLE"


def test_weights_are_configurable(engine):
    """Doubling a weight changes the score in the predicted direction."""
    from app.config import AttentionWeights

    payload = dict(
        change_percent=4.0,
        technical=_with(_calm_technical(), move_zscore=2.5, volume_ratio20=1.0),
    )
    default = SignalEngine().evaluate(_base_input(**payload))
    heavy_price = SignalEngine(AttentionWeights(price_move=50.0)).evaluate(_base_input(**payload))
    assert heavy_price.score > default.score


# ─────────────────────────────────────────────────────────────────────────────
# Event detection
# ─────────────────────────────────────────────────────────────────────────────


def test_detects_volume_spike(engine):
    result = engine.evaluate(
        _base_input(technical=_with(_calm_technical(), volume_ratio20=2.6))
    )
    assert EventType.VOLUME_SPIKE in {e.type for e in result.events}


def test_no_volume_spike_below_threshold(engine):
    result = engine.evaluate(
        _base_input(technical=_with(_calm_technical(), volume_ratio20=1.5))
    )
    assert EventType.VOLUME_SPIKE not in {e.type for e in result.events}


def test_detects_volume_divergence_when_price_is_flat(engine):
    result = engine.evaluate(
        _base_input(change_percent=0.3, technical=_with(_calm_technical(), volume_ratio20=3.1))
    )
    types = {e.type for e in result.events}
    assert EventType.VOLUME_DIVERGENCE in types


def test_detects_ma_crossover_only_on_transition(engine):
    # Yesterday below the 50-day, today above it -> crossover.
    crossing = engine.evaluate(
        _base_input(
            price=101.0,
            technical=_with(_calm_technical(101.0), sma50=100.0, prev_sma50=100.0, prev_close=99.0),
        )
    )
    assert any(
        e.type == EventType.MA_CROSSOVER and e.metrics.get("period") == 50
        for e in crossing.events
    )

    # Above on both days -> no event.
    steady = engine.evaluate(
        _base_input(
            price=105.0,
            technical=_with(_calm_technical(105.0), sma50=100.0, prev_sma50=100.0, prev_close=104.0),
        )
    )
    assert not any(
        e.type == EventType.MA_CROSSOVER and e.metrics.get("period") == 50
        for e in steady.events
    )


def test_detects_breakout_and_breakdown(engine):
    up = engine.evaluate(
        _base_input(price=112.0, technical=_with(_calm_technical(112.0), resistance60=110.0))
    )
    assert EventType.BREAKOUT in {e.type for e in up.events}

    down = engine.evaluate(
        _base_input(price=88.0, change_percent=-4.0,
                    technical=_with(_calm_technical(88.0), support60=90.0))
    )
    assert EventType.BREAKDOWN in {e.type for e in down.events}


def test_detects_new_52_week_high_against_prior_range(engine):
    result = engine.evaluate(
        _base_input(price=126.0, technical=_with(_calm_technical(126.0), week52_high=125.0))
    )
    assert EventType.NEW_HIGH in {e.type for e in result.events}


def test_detects_gap(engine):
    result = engine.evaluate(_base_input(previous_close=100.0, open_price=103.0, price=103.5))
    assert EventType.GAP_UP in {e.type for e in result.events}


def test_news_spike_requires_multiple_recent_items(engine):
    now = utcnow()
    result = engine.evaluate(
        _base_input(
            news=[
                ScoredNews("Item one", "negative", 0.7, "Regulatory", now - timedelta(hours=1)),
                ScoredNews("Item two", "negative", 0.7, "Regulatory", now - timedelta(hours=2)),
                ScoredNews("Item three", "negative", 0.6, "Regulatory", now - timedelta(hours=3)),
            ],
        )
    )
    spike = next((e for e in result.events if e.type == EventType.NEWS_SPIKE), None)
    assert spike is not None
    assert spike.metrics["count"] == 3
    assert spike.metrics["tone"] == "negative"


def test_stale_news_does_not_spike(engine):
    old = utcnow() - timedelta(days=4)
    result = engine.evaluate(
        _base_input(news=[ScoredNews(f"Old item {i}", "positive", 0.7, "X", old) for i in range(5)])
    )
    assert EventType.NEWS_SPIKE not in {e.type for e in result.events}


def test_user_threshold_event(engine):
    result = engine.evaluate(_base_input(change_percent=-3.1, user_threshold_percent=2.5))
    threshold_events = [e for e in result.events if e.type == EventType.USER_THRESHOLD]
    assert len(threshold_events) == 1
    assert result.top_reason == "Your alert triggered"


# ─────────────────────────────────────────────────────────────────────────────
# Stale / conflicting data
# ─────────────────────────────────────────────────────────────────────────────


def test_stale_data_emits_warning_and_lowers_confidence(engine):
    fresh = engine.evaluate(_base_input())
    stale = engine.evaluate(
        _base_input(
            data_quality=DataQuality(
                freshness="STALE", age_seconds=1400, source="test", is_delayed=True,
                verification="single_source",
            )
        )
    )
    assert stale.confidence < fresh.confidence
    assert any(e.type == EventType.DATA_QUALITY_WARNING for e in stale.events)


def test_data_quality_events_do_not_earn_attention_points(engine):
    """A provider outage must not be mistaken for a calm market — or a hot one."""
    clean = engine.evaluate(_base_input())
    conflicted = engine.evaluate(
        _base_input(
            data_quality=DataQuality(
                freshness="FRESH", age_seconds=20, source="test",
                verification="conflict", has_conflict=True,
                conflict_note="Source A and B disagree by 3.1%",
            )
        )
    )
    # The price/volume/etc components are identical; only confidence and the
    # DATA event differ.
    assert clean.score == pytest.approx(conflicted.score, abs=0.05)
    assert conflicted.confidence < clean.confidence
    assert "DATA_CONFLICT" in {e.fingerprint for e in conflicted.events}


def test_confidence_rises_with_corroboration(engine):
    isolated = engine.evaluate(_base_input(change_percent=5.0))
    corroborated = engine.evaluate(
        _base_input(
            change_percent=5.0,
            technical=_with(_calm_technical(), volume_ratio20=2.5, move_zscore=2.0),
            news=[
                ScoredNews("A", "positive", 0.8, "X", utcnow() - timedelta(minutes=20)),
                ScoredNews("B", "positive", 0.8, "X", utcnow() - timedelta(minutes=40)),
                ScoredNews("C", "positive", 0.8, "X", utcnow() - timedelta(minutes=60)),
            ],
        )
    )
    assert corroborated.confidence > isolated.confidence


# ─────────────────────────────────────────────────────────────────────────────
# Since last visit
# ─────────────────────────────────────────────────────────────────────────────


def test_first_look_has_no_baseline(engine):
    result = engine.evaluate(_base_input())
    assert result.since_last_visit.has_baseline is False


def test_since_last_visit_computes_price_delta(engine):
    result = engine.evaluate(
        _base_input(
            price=110.0,
            baseline=Baseline(
                last_seen_price=100.0, last_seen_score=20.0, last_seen_band="STABLE",
                last_reviewed_at=utcnow() - timedelta(hours=3),
            ),
        )
    )
    since = result.since_last_visit
    assert since.has_baseline
    assert since.price_change_percent == pytest.approx(10.0, abs=0.01)
    assert since.is_meaningful is True


def test_small_move_since_visit_is_not_meaningful(engine):
    result = engine.evaluate(
        _base_input(
            price=100.4,
            baseline=Baseline(
                last_seen_price=100.0, last_seen_score=12.0, last_seen_band="STABLE",
                last_seen_event_fingerprints=[], last_reviewed_at=utcnow() - timedelta(hours=2),
            ),
        )
    )
    assert result.since_last_visit.is_meaningful is False
    assert result.since_last_visit.headline == "No meaningful change"


def test_new_signal_since_visit_is_meaningful_even_without_price_move(engine):
    """A quiet crossover the user has not seen still counts as a change."""
    result = engine.evaluate(
        _base_input(
            price=101.0,
            change_percent=0.6,
            technical=_with(_calm_technical(101.0), sma50=100.0, prev_sma50=100.0, prev_close=99.4),
            baseline=Baseline(
                last_seen_price=100.6, last_seen_score=18.0, last_seen_band="STABLE",
                last_seen_event_fingerprints=[], last_reviewed_at=utcnow() - timedelta(hours=2),
            ),
        )
    )
    assert result.since_last_visit.is_meaningful is True
    assert result.since_last_visit.new_signals


def test_resolved_signals_are_reported(engine):
    """A signal that was there last time and is now gone is surfaced too."""
    result = engine.evaluate(
        _base_input(
            baseline=Baseline(
                last_seen_price=99.8, last_seen_score=60.0, last_seen_band="WATCH",
                last_seen_event_fingerprints=["VOLUME_SPIKE", "PRICE_MOVE:up"],
                last_reviewed_at=utcnow() - timedelta(hours=4),
            ),
        )
    )
    assert set(result.since_last_visit.resolved_signals) >= {"VOLUME_SPIKE"}


def test_escalation_is_detected(engine):
    result = engine.evaluate(
        _base_input(
            change_percent=7.0,
            technical=_with(_calm_technical(), volume_ratio20=2.6, move_zscore=2.2),
            news=[
                ScoredNews("A", "positive", 0.8, "X", utcnow() - timedelta(minutes=15)),
                ScoredNews("B", "positive", 0.8, "X", utcnow() - timedelta(minutes=45)),
                ScoredNews("C", "positive", 0.8, "X", utcnow() - timedelta(minutes=75)),
            ],
            baseline=Baseline(
                last_seen_price=93.0, last_seen_score=28.0, last_seen_band="STABLE",
                last_seen_event_fingerprints=[], last_reviewed_at=utcnow() - timedelta(hours=5),
            ),
        )
    )
    assert result.since_last_visit.escalated is True


# ─────────────────────────────────────────────────────────────────────────────
# Determinism
# ─────────────────────────────────────────────────────────────────────────────


def test_engine_is_deterministic(engine):
    payload = _base_input(
        change_percent=3.3, technical=_with(_calm_technical(), volume_ratio20=2.1)
    )
    a = engine.evaluate(payload)
    b = engine.evaluate(payload)
    assert a.score == b.score
    assert [e.fingerprint for e in a.events] == [e.fingerprint for e in b.events]
    assert a.why_it_matters == b.why_it_matters


# ── helpers ─────────────────────────────────────────────────────────────────


def _with(state: TechnicalState, **changes) -> TechnicalState:
    from dataclasses import replace

    return replace(state, **changes)
