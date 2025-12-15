
from astra_modules.guardian.guardian_v7 import guardian_log
from core.cache_manager import CacheManager

CACHE_TTL = 3600  # 1 hour


def adaptive_cache(key, compute_fn):
    """Use cached result if fresh; else recompute and store."""
    value = CacheManager.get(key)
    if value is not None:
        guardian_log(f"[Cache] {key} restored from cache.")
        return value
    guardian_log(f"[Cache] Recomputing {key}...")
    value = compute_fn()
    CacheManager.set(key, value, ttl_seconds=CACHE_TTL)
    guardian_log(f"[Cache] {key} cached successfully.")
    return value
