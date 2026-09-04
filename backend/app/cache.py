"""Caching, behind an interface.

The in-process implementation is the default and is entirely sufficient for a
single-node deployment. `RedisCache` exists so that horizontal scaling is a
configuration change rather than a rewrite — see README → Scalability.

The one non-obvious feature is `get_stale()`: when an upstream provider fails,
serving the last known value *clearly labelled as stale* is far better than
serving an error page. So expired entries are retained rather than evicted, up
to a grace multiplier.
"""

from __future__ import annotations

import abc
import fnmatch
import threading
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    stored_at: float
    expires_at: float

    @property
    def is_fresh(self) -> bool:
        return time.time() < self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.stored_at


class Cache(abc.ABC):
    @abc.abstractmethod
    def get(self, key: str) -> Any | None: ...

    @abc.abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int) -> None: ...

    @abc.abstractmethod
    def get_stale(self, key: str, max_age_seconds: float) -> tuple[Any, float] | None:
        """Return `(value, age)` even if expired, provided it is not too old."""

    @abc.abstractmethod
    def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    def clear(self, pattern: str = "*") -> int: ...


class InMemoryCache(Cache):
    """Thread-safe TTL cache with stale-read support."""

    # Retain expired entries for this multiple of their TTL, as fallback data.
    STALE_GRACE_MULTIPLIER = 40

    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = threading.RLock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            if entry.is_fresh:
                return entry.value
            return None

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        now = time.time()
        with self._lock:
            self._data[key] = CacheEntry(value, now, now + ttl_seconds)
            # Opportunistic eviction; the working set here is tiny (a few
            # hundred symbols), so a full sweep is cheaper than a heap.
            if len(self._data) > 5000:
                self._evict_locked()

    def get_stale(self, key: str, max_age_seconds: float) -> tuple[Any, float] | None:
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                return None
            age = entry.age_seconds
            return (entry.value, age) if age <= max_age_seconds else None

    def delete(self, key: str) -> None:
        with self._lock:
            self._data.pop(key, None)

    def clear(self, pattern: str = "*") -> int:
        with self._lock:
            keys = [k for k in self._data if fnmatch.fnmatch(k, pattern)]
            for k in keys:
                del self._data[k]
            return len(keys)

    def _evict_locked(self) -> None:
        now = time.time()
        for key, entry in list(self._data.items()):
            grace = (entry.expires_at - entry.stored_at) * self.STALE_GRACE_MULTIPLIER
            if now > entry.stored_at + grace:
                del self._data[key]

    def stats(self) -> dict:
        with self._lock:
            fresh = sum(1 for e in self._data.values() if e.is_fresh)
            return {"backend": "memory", "entries": len(self._data), "fresh": fresh}


class RedisCache(Cache):  # pragma: no cover - opt-in path
    """Redis-backed cache for multi-node deployments.

    Values are pickled, so this is for trusted internal use only. Stale reads
    are implemented with a companion key holding the store timestamp, and a
    physical TTL longer than the logical one.
    """

    STALE_GRACE_MULTIPLIER = 40

    def __init__(self, url: str):
        import pickle

        import redis

        self._pickle = pickle
        self._client = redis.Redis.from_url(url)
        self._client.ping()

    def get(self, key: str) -> Any | None:
        raw = self._client.get(f"sw:v:{key}")
        if raw is None:
            return None
        expires = self._client.get(f"sw:e:{key}")
        if expires and time.time() > float(expires):
            return None
        return self._pickle.loads(raw)

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        physical = int(ttl_seconds * self.STALE_GRACE_MULTIPLIER)
        pipe = self._client.pipeline()
        pipe.setex(f"sw:v:{key}", physical, self._pickle.dumps(value))
        pipe.setex(f"sw:e:{key}", physical, str(time.time() + ttl_seconds))
        pipe.setex(f"sw:t:{key}", physical, str(time.time()))
        pipe.execute()

    def get_stale(self, key: str, max_age_seconds: float) -> tuple[Any, float] | None:
        raw = self._client.get(f"sw:v:{key}")
        stored = self._client.get(f"sw:t:{key}")
        if raw is None or stored is None:
            return None
        age = time.time() - float(stored)
        return (self._pickle.loads(raw), age) if age <= max_age_seconds else None

    def delete(self, key: str) -> None:
        self._client.delete(f"sw:v:{key}", f"sw:e:{key}", f"sw:t:{key}")

    def clear(self, pattern: str = "*") -> int:
        count = 0
        for key in self._client.scan_iter(match=f"sw:v:{pattern}"):
            self._client.delete(key)
            count += 1
        return count

    def stats(self) -> dict:
        return {"backend": "redis", "entries": self._client.dbsize()}


_cache: Cache | None = None


def get_cache() -> Cache:
    """Process-wide cache singleton. Falls back to memory if Redis is absent."""
    global _cache
    if _cache is not None:
        return _cache

    from app.config import settings

    if settings.redis_url:
        try:
            _cache = RedisCache(settings.redis_url)
            return _cache
        except Exception:  # noqa: BLE001 - Redis is strictly optional
            import logging

            logging.getLogger(__name__).warning(
                "Redis unavailable at %s; using in-process cache", settings.redis_url
            )
    _cache = InMemoryCache()
    return _cache
