"""In-memory TTL cache service (replaces Redis for MVP)."""

import threading
import time
from typing import Any

from app.config import FUND_NAME_CACHE_TTL, NAV_HISTORY_CACHE_TTL, STOCK_CACHE_TTL


class CacheService:
    """Thread-safe in-memory cache with TTL support."""

    def __init__(self, default_ttl: int = 60):
        self._store: dict[str, tuple[Any, float]] = {}
        self._default_ttl = default_ttl
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if time.time() > expires_at:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        ttl = ttl if ttl is not None else self._default_ttl
        expires_at = time.time() + ttl
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


# Global cache instances — TTLs from config
stock_cache = CacheService(default_ttl=STOCK_CACHE_TTL)
nav_history_cache = CacheService(default_ttl=NAV_HISTORY_CACHE_TTL)
fund_name_cache = CacheService(default_ttl=FUND_NAME_CACHE_TTL)
