"""
cache_manager.py — Lightweight local caching utility for Astra Intelligence.
Prevents redundant API calls and supports Guardian smart refresh logic.
"""

import time
from core.guardian.guardian_v7 import guardian_log

_cache = {}

class CacheManager:
    @staticmethod
    def set(key, value, ttl=300):
        """Store a value with time-to-live (TTL) in seconds."""
        _cache[key] = {"value": value, "ts": time.time(), "ttl": ttl}
        guardian_log.info(f"[CacheManager] Cached {key} for {ttl}s.")

    @staticmethod
    def get(key):
        """Retrieve cached value if still valid."""
        entry = _cache.get(key)
        if not entry:
            return None
        age = time.time() - entry["ts"]
        if age > entry["ttl"]:
            guardian_log.info(f"[CacheManager] Cache expired for {key}.")
            del _cache[key]
            return None
        guardian_log.info(f"[CacheManager] Cache hit for {key}. (age={age:.1f}s)")
        return entry["value"]

    @staticmethod
    def clear():
        """Clear all cached data."""
        _cache.clear()
        guardian_log.info("[CacheManager] Cache cleared.")

    @staticmethod
    def size():
        """Return number of current cached items."""
        return len(_cache)
