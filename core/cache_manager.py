import os
import json
import time
from typing import Any, Callable

CACHE_PATH = "state/cache_store.json"


class CacheManager:
    """Simple TTL-based caching system with disk persistence."""

    _cache = {}
    _ttl = {}

    @staticmethod
    def get(key: str) -> Any:
        """Retrieve from memory or disk if valid."""
        if key in CacheManager._cache:
            if time.time() < CacheManager._ttl.get(key, 0):
                return CacheManager._cache[key]
            else:
                CacheManager._cache.pop(key, None)
        # Fallback to disk
        if os.path.exists(CACHE_PATH):
            try:
                with open(CACHE_PATH, "r") as f:
                    data = json.load(f)
                    if key in data:
                        return data[key]
            except Exception:
                pass
        return None

    @staticmethod
    def set(key: str, value: Any, ttl_seconds: int = 3600):
        """Store in memory and disk."""
        CacheManager._cache[key] = value
        CacheManager._ttl[key] = time.time() + ttl_seconds
        os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
        try:
            with open(CACHE_PATH, "r") as f:
                data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            data = {}
        data[key] = value
        with open(CACHE_PATH, "w") as f:
            json.dump(data, f)

    @staticmethod
    def get_or_set(key: str, loader: Callable, ttl_seconds: int = 3600):
        """Get from cache or compute and set."""
        value = CacheManager.get(key)
        if value is not None:
            return value
        value = loader()
        CacheManager.set(key, value, ttl_seconds)
        return value

# Phase 2.4 temporary stub to prevent cache_rebuilder failure
def set(*args, **kwargs):
    print("[CacheManager] ⚠️ set() called (stubbed for Phase 2.4)")
    return None
