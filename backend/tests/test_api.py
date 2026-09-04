"""API-level integration tests.

These exercise the routes end to end against a fresh in-memory database and the
deterministic demo provider.
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def seeded(client):
    """A client whose demo user has the starter watchlist."""
    response = client.post("/api/watchlists/starter")
    assert response.status_code == 201
    return client


# ─────────────────────────────────────────────────────────────────────────────
# Health & config
# ─────────────────────────────────────────────────────────────────────────────


def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "ok"
    assert body["provider_is_demo"] is True


def test_config_exposes_weights_that_sum_to_100(client):
    body = client.get("/api/config").json()
    assert body["weights_total"] == pytest.approx(100.0)
    assert set(body["weights"]) == {
        "price_move", "volume_anomaly", "technical", "news", "volatility", "recency",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Watchlist CRUD
# ─────────────────────────────────────────────────────────────────────────────


def test_watchlist_crud_lifecycle(client):
    # A sibling, so the one under test is not the user's only list (deleting
    # your last watchlist is deliberately blocked).
    client.post("/api/watchlists", json={"name": "Keep"})

    created = client.post("/api/watchlists", json={"name": "Growth"}).json()
    assert created["name"] == "Growth"
    wl_id = created["id"]

    renamed = client.patch(f"/api/watchlists/{wl_id}", json={"name": "High Growth"}).json()
    assert renamed["name"] == "High Growth"

    listing = client.get("/api/watchlists").json()
    assert any(w["id"] == wl_id for w in listing)

    assert client.delete(f"/api/watchlists/{wl_id}").status_code == 200
    listing = client.get("/api/watchlists").json()
    assert not any(w["id"] == wl_id for w in listing)


def test_duplicate_watchlist_name_is_rejected(client):
    client.post("/api/watchlists", json={"name": "Tech"})
    dup = client.post("/api/watchlists", json={"name": "tech"})
    assert dup.status_code == 409
    assert "already have a watchlist" in dup.json()["error"].lower()


def test_blank_watchlist_name_is_rejected(client):
    resp = client.post("/api/watchlists", json={"name": "   "})
    assert resp.status_code == 422


def test_cannot_delete_your_last_watchlist(client):
    only = client.post("/api/watchlists", json={"name": "Only"}).json()
    resp = client.delete(f"/api/watchlists/{only['id']}")
    assert resp.status_code == 409


# ─────────────────────────────────────────────────────────────────────────────
# Stock add / remove / reorder
# ─────────────────────────────────────────────────────────────────────────────


def test_add_and_remove_stock(client):
    wl = client.post("/api/watchlists", json={"name": "Chips"}).json()
    added = client.post(f"/api/watchlists/{wl['id']}/stocks", json={"symbol": "NVDA"}).json()
    assert [item["stock"]["symbol"] for item in added["items"]] == ["NVDA"]

    dup = client.post(f"/api/watchlists/{wl['id']}/stocks", json={"symbol": "nvda"})
    assert dup.status_code == 409

    removed = client.request(
        "DELETE", f"/api/watchlists/{wl['id']}/stocks/NVDA"
    ).json()
    assert removed["items"] == []


def test_add_unknown_symbol_is_404(client):
    wl = client.post("/api/watchlists", json={"name": "X"}).json()
    resp = client.post(f"/api/watchlists/{wl['id']}/stocks", json={"symbol": "ZZZZ"})
    assert resp.status_code == 404


def test_reorder_items(client):
    wl = client.post("/api/watchlists", json={"name": "Order"}).json()
    for symbol in ("NVDA", "TSLA", "MSFT"):
        client.post(f"/api/watchlists/{wl['id']}/stocks", json={"symbol": symbol})

    reordered = client.post(
        f"/api/watchlists/{wl['id']}/reorder",
        json={"ordered_symbols": ["MSFT", "NVDA", "TSLA"]},
    ).json()
    assert [i["stock"]["symbol"] for i in reordered["items"]] == ["MSFT", "NVDA", "TSLA"]


def test_threshold_can_be_set(client):
    wl = client.post("/api/watchlists", json={"name": "Alerts"}).json()
    client.post(f"/api/watchlists/{wl['id']}/stocks", json={"symbol": "TSLA"})
    updated = client.patch(
        f"/api/watchlists/{wl['id']}/stocks/TSLA", json={"threshold_percent": 2.5}
    ).json()
    item = next(i for i in updated["items"] if i["stock"]["symbol"] == "TSLA")
    assert item["threshold_percent"] == 2.5


# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────


def test_search_matches_symbol_and_name(client):
    by_symbol = client.get("/api/stocks/search?q=NVDA").json()
    assert by_symbol and by_symbol[0]["symbol"] == "NVDA"

    by_name = client.get("/api/stocks/search?q=nvidia").json()
    assert any(m["symbol"] == "NVDA" for m in by_name)


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────


def test_first_run_dashboard_offers_onboarding(client):
    body = client.get("/api/dashboard").json()
    assert body["onboarding"]["is_first_run"] is True
    assert "NVDA" in body["onboarding"]["suggested"]


def test_dashboard_returns_everything_in_one_call(seeded):
    body = seeded.get("/api/dashboard").json()
    for key in (
        "market_status", "summary", "since_last_visit", "attention_queue",
        "stable_stocks", "watchlists", "data_quality", "recent_events", "config",
    ):
        assert key in body, f"missing dashboard key: {key}"
    assert body["summary"]["tracked"] == 5
    # Attention queue is sorted by score, descending.
    scores = [row["score"] for row in body["attention_queue"]]
    assert scores == sorted(scores, reverse=True)


def test_dashboard_attention_queue_has_explainable_rows(seeded):
    body = seeded.get("/api/dashboard").json()
    for row in body["attention_queue"]:
        assert row["top_reason"]
        assert 0 <= row["score"] <= 100
        assert row["band"] in {"HIGH_ATTENTION", "WATCH", "STABLE"}


# ─────────────────────────────────────────────────────────────────────────────
# Stock detail
# ─────────────────────────────────────────────────────────────────────────────


def test_stock_detail_is_fully_explained(seeded):
    body = seeded.get("/api/stocks/NVDA").json()
    assert body["symbol"] == "NVDA"
    assert body["why_it_matters"]
    assert len(body["explanation"]["components"]) == 6
    assert body["timeline"] is not None
    # The score equals the sum of its components (clamped).
    parts = sum(c["points"] for c in body["explanation"]["components"])
    assert body["score"] == pytest.approx(min(100.0, round(parts, 1)), abs=0.11)


def test_history_endpoint_returns_overlays(seeded):
    body = seeded.get("/api/stocks/NVDA/history?range=3M").json()
    assert body["points"]
    # Later points carry moving-average overlays.
    assert any(p["sma20"] is not None for p in body["points"])
    assert any(p["sma50"] is not None for p in body["points"])


def test_untracked_stock_detail_is_404(client):
    assert client.get("/api/stocks/NVDA").status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# The core loop: visit -> change -> return -> detected -> reviewed
# ─────────────────────────────────────────────────────────────────────────────


def test_core_product_loop(seeded):
    client = seeded

    # Start from the quiet world and make it the reviewed baseline.
    client.post("/api/demo/replay/reset")
    baseline = client.get("/api/dashboard").json()
    assert baseline["since_last_visit"]["count"] == 0

    # The market moves while the user is away.
    client.post("/api/demo/replay/step", json={"step": 4})

    # The user returns: the change is waiting for them.
    after = client.get("/api/dashboard").json()
    assert after["since_last_visit"]["count"] > 0
    nvda_change = next(
        (c for c in after["since_last_visit"]["changes"] if c["symbol"] == "NVDA"), None
    )
    assert nvda_change is not None
    assert nvda_change["since_last_visit"]["score_delta"] > 20
    assert nvda_change["band"] == "HIGH_ATTENTION"

    # They acknowledge NVDA specifically.
    reviewed = client.post("/api/changes/mark-reviewed", json={"symbols": ["NVDA"]}).json()
    assert reviewed["reviewed"] == 1

    # NVDA is no longer "since your last visit"; the rest still is.
    settled = client.get("/api/dashboard").json()
    symbols_still_changed = {c["symbol"] for c in settled["since_last_visit"]["changes"]}
    assert "NVDA" not in symbols_still_changed
    assert len(symbols_still_changed) > 0


def test_mark_all_reviewed_clears_the_section(seeded):
    client = seeded
    client.post("/api/demo/replay/step", json={"step": 4})
    assert client.get("/api/dashboard").json()["since_last_visit"]["count"] > 0

    client.post("/api/changes/mark-reviewed", json={})
    assert client.get("/api/changes/since-last-visit").json()["count"] == 0


def test_opening_the_dashboard_does_not_move_the_baseline(seeded):
    """Loading the page must not silently consume the 'since last visit' deltas."""
    client = seeded
    client.post("/api/demo/replay/step", json={"step": 4})

    first = client.get("/api/dashboard").json()["since_last_visit"]["count"]
    second = client.get("/api/dashboard").json()["since_last_visit"]["count"]
    third = client.get("/api/dashboard").json()["since_last_visit"]["count"]
    assert first == second == third > 0


# ─────────────────────────────────────────────────────────────────────────────
# Replay
# ─────────────────────────────────────────────────────────────────────────────


def test_replay_advances_the_world_and_rerates(seeded):
    client = seeded
    client.post("/api/demo/replay/reset")

    def nvda_score():
        body = client.get("/api/dashboard").json()
        rows = body["attention_queue"] + body["stable_stocks"]
        return next(r["score"] for r in rows if r["symbol"] == "NVDA")

    quiet = nvda_score()
    client.post("/api/demo/replay/step", json={"step": 4})
    loud = nvda_score()

    assert loud - quiet > 30, f"expected a large re-rate, got {quiet} -> {loud}"


def test_replay_reset_rebaselines(seeded):
    client = seeded
    client.post("/api/demo/replay/step", json={"step": 4})
    client.post("/api/changes/mark-reviewed", json={})

    reset = client.post("/api/demo/replay/reset").json()
    assert reset["current_step"] == 0
    # After a reset the quiet world is the new baseline: nothing outstanding.
    assert client.get("/api/changes/since-last-visit").json()["count"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# Error handling
# ─────────────────────────────────────────────────────────────────────────────


def test_validation_error_is_structured(client):
    resp = client.post("/api/watchlists", json={})
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "VALIDATION_ERROR"
    assert "error" in body


def test_unknown_route_is_404(client):
    assert client.get("/api/nope").status_code == 404
