"""Replay world state.

The demo replay is not a front-end animation. Advancing the step mutates the
world the provider reports, so the signal engine genuinely re-detects events
from scratch and the attention score genuinely re-rates. That state is
persisted, so it survives a reload mid-presentation.

Concurrency note
----------------
`get_world_step()` is on the hot path — it is consulted on every provider call.
It must therefore **never open a database session itself**. On SQLite with a
shared connection, a nested session opened in the middle of a request would roll
back the request's own uncommitted writes when it closed. So the step is loaded
into a process-wide cache exactly once, at startup (`load_world_step()`), and
thereafter only `set_world_step()` — an explicit, deliberate action — touches
the database.
"""

from __future__ import annotations

import logging
import threading

from app.models import AppState
from app.providers.demo import FINAL_REPLAY_STEP, REPLAY_STEPS, REPLAY_SYMBOL
from app.timeutil import utcnow

logger = logging.getLogger(__name__)

_WORLD_KEY = "world"
_lock = threading.RLock()
_cached_step: int | None = None


def _read_step_from_db() -> int:
    """Read the persisted step. Only safe to call when no request txn is open."""
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(AppState, _WORLD_KEY)
        if row and isinstance(row.value, dict) and "step" in row.value:
            return max(0, min(int(row.value["step"]), FINAL_REPLAY_STEP))
    except Exception as exc:  # noqa: BLE001 - a missing table at first boot is fine
        logger.debug("world step not readable yet: %s", exc)
    finally:
        db.close()
    return FINAL_REPLAY_STEP


def load_world_step() -> int:
    """Prime the cache from the database. Call once, at application startup."""
    global _cached_step
    with _lock:
        _cached_step = _read_step_from_db()
        return _cached_step


def get_world_step() -> int:
    """Current replay frame. Pure cache read — never hits the database."""
    step = _cached_step
    return FINAL_REPLAY_STEP if step is None else step


def set_world_step(step: int) -> int:
    """Persist a new replay frame and invalidate downstream caches.

    This is the only function here that writes to the database, and it is only
    ever called from an explicit user action (the replay endpoints, the seed
    script), never from within request-handling of unrelated work.
    """
    global _cached_step
    from app.database import SessionLocal
    from app.providers.registry import reset_market_data_service

    step = max(0, min(int(step), FINAL_REPLAY_STEP))
    with _lock:
        db = SessionLocal()
        try:
            row = db.get(AppState, _WORLD_KEY)
            if row is None:
                db.add(AppState(key=_WORLD_KEY, value={"step": step}))
            else:
                row.value = {"step": step}
                row.updated_at = utcnow()
            db.commit()
        finally:
            db.close()
        _cached_step = step

    # The provider's output has changed, so every cached derivative is stale.
    reset_market_data_service()
    return step


def reset_cache() -> None:
    """Drop the in-process copy (used by tests and after a reseed)."""
    global _cached_step
    with _lock:
        _cached_step = None


def replay_script() -> list[dict]:
    return [
        {
            "step": i,
            "clock": s.clock,
            "caption": s.caption,
            "symbol": REPLAY_SYMBOL,
            "change_percent": s.change_percent,
            "volume_ratio": s.volume_ratio,
            "news_count": s.news_count,
        }
        for i, s in enumerate(REPLAY_STEPS)
    ]
