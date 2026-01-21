import time

import requests

from astra_modules.guardian.guardian_v7 import guardian_log

_cache = {}
_last_call = {}


def rate_safe_get(
    url, params=None, headers=None, key_name="TwelveData", ttl=60, cooldown=7
):
    """Fetch URL safely with caching & per-source cooldown."""
    global _cache, _last_call
    key = f"{url}|{params}"
    now = time.time()

    # Reuse cached result if < ttl seconds old
    if key in _cache and now - _cache[key]["time"] < ttl:
        guardian_log(f"[Cache] Reusing {key_name} result for {params}")
        return _cache[key]["data"]

    # Enforce cooldown between provider calls
    last = _last_call.get(key_name, 0)
    if now - last < cooldown:
        wait = round(cooldown - (now - last), 2)
        guardian_log(
            f"[RateSafe] Waiting {wait}s before next {key_name} call...")
        time.sleep(wait)

    try:
        guardian_log(f"[RateSafe] Fetching from {key_name}: {params}")
        r = requests.get(url, params=params or {},
                         headers=headers or {}, timeout=6)
        _last_call[key_name] = time.time()
        if r.status_code == 200:
            data = r.json()
            _cache[key] = {"data": data, "time": now}
            return data
        guardian_log(f"[RateSafe] ⚠️ {key_name} returned {r.status_code}")
    except Exception as e:
        guardian_log(f"[RateSafe] ❌ {key_name} failed: {e}")
    return {}
