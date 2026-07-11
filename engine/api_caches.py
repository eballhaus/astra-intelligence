from __future__ import annotations

import time
from threading import Lock
import os

_LOCK = Lock()
_CACHE = {}
_MAX_ENTRIES = max(100, int(float(os.getenv("ASTRA_SHARED_DATA_CACHE_MAX_ENTRIES", "5000"))))
_STATS = {"hits": 0, "misses": 0, "stale_hits": 0, "sets": 0, "evictions": 0, "entries": 0}


def _make_key(namespace, provider, symbol, dataset, resolution=None):
    return (str(namespace or ""), str(provider or ""), str(symbol or ""), str(dataset or ""), str(resolution or ""))


def get_cache(namespace, provider, symbol, dataset, resolution=None, ttl=60):
    key = _make_key(namespace, provider, symbol, dataset, resolution=resolution)
    now = time.time()
    with _LOCK:
        rec = _CACHE.get(key)
        if not rec:
            _STATS["misses"] += 1
            return None
        if (now - float(rec.get("ts", 0.0))) > float(ttl or 0):
            _STATS["misses"] += 1
            _STATS["stale_hits"] += 1
            return None
        _STATS["hits"] += 1
        return rec.get("payload")


def set_cache(namespace, provider, symbol, dataset, payload, resolution=None):
    key = _make_key(namespace, provider, symbol, dataset, resolution=resolution)
    with _LOCK:
        if key not in _CACHE and len(_CACHE) >= _MAX_ENTRIES:
            oldest = min(_CACHE, key=lambda item: float((_CACHE.get(item) or {}).get("ts", 0.0)))
            _CACHE.pop(oldest, None)
            _STATS["evictions"] += 1
        _CACHE[key] = {"payload": payload, "ts": time.time()}
        _STATS["sets"] += 1
        _STATS["entries"] = len(_CACHE)


def cache_metrics():
    with _LOCK:
        now = time.time()
        ages = [max(0.0, now - float((rec or {}).get("ts", 0.0))) for rec in _CACHE.values()]
        out = dict(_STATS)
        out.update({
            "max_entries": int(_MAX_ENTRIES),
            "bounded_cache": True,
            "oldest_entry_age_seconds": round(max(ages), 3) if ages else 0.0,
            "newest_entry_age_seconds": round(min(ages), 3) if ages else 0.0,
            "cache_hit_rate_pct": round((out["hits"] / max(1, out["hits"] + out["misses"])) * 100.0, 3),
        })
        return out
