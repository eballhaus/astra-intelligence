"""
Astra 7.0 - Caching Utilities (Phase 45)
----------------------------------------
Provides:
    • cache_get(key)
    • cache_set(key, value)
    • timed_cache decorator
Caches are stored in-memory (per session).
"""

import time
import functools

# Simple in-memory cache dictionary
_CACHE = {}
_CACHE_EXPIRY = {}


# -------------------------------------------------------
# Direct cache accessors
# -------------------------------------------------------
def cache_get(key):
    """Return cached value if not expired, else None."""
    if key in _CACHE and key in _CACHE_EXPIRY:
        if time.time() < _CACHE_EXPIRY[key]:
            return _CACHE[key]
        # expired
        _CACHE.pop(key, None)
        _CACHE_EXPIRY.pop(key, None)
    return None


def cache_set(key, value, ttl=300):
    """Cache value for (ttl) seconds."""
    _CACHE[key] = value
    _CACHE_EXPIRY[key] = time.time() + ttl


# -------------------------------------------------------
# Decorator for timed cache (optional use)
# -------------------------------------------------------
def timed_cache(seconds=300):
    """Simple time-based cache decorator."""
    def wrapper(func):
        cache = {}

        @functools.wraps(func)
        def inner(*args):
            now = time.time()

            if args in cache:
                value, timestamp = cache[args]
                if now - timestamp < seconds:
                    return value

            result = func(*args)
            cache[args] = (result, now)
            return result

        return inner
    return wrapper
