from __future__ import annotations

import time
from threading import Lock

_LOCK = Lock()
_CACHE = {}
_STATS = {"hits": 0, "misses": 0, "sets": 0, "entries": 0}


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
            return None
        _STATS["hits"] += 1
        return rec.get("payload")


def set_cache(namespace, provider, symbol, dataset, payload, resolution=None):
    key = _make_key(namespace, provider, symbol, dataset, resolution=resolution)
    with _LOCK:
        _CACHE[key] = {"payload": payload, "ts": time.time()}
        _STATS["sets"] += 1
        _STATS["entries"] = len(_CACHE)


def cache_metrics():
    with _LOCK:
        return dict(_STATS)

