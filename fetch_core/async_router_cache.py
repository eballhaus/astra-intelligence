import asyncio
import aiohttp
import random
import time
import json
from pathlib import Path
from fetch_core.api_router import API_POOL

CACHE_FILE = Path("state/last_good_api.json")


async def fetch_single(session, name):
    base = API_POOL[name]["base"]
    start = time.time()
    try:
        async with session.get(base, timeout=3) as r:
            return name, r.status, round(time.time() - start, 2)
    except Exception as e:
        return name, str(e), None


async def fetch_all():
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_single(session, name) for name in API_POOL.keys()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid = [r for r in results if isinstance(r, tuple) and r[1] == 200]
        if valid:
            best = sorted(valid, key=lambda x: x[2])[0]
            CACHE_FILE.parent.mkdir(exist_ok=True)
            with open(CACHE_FILE, "w") as f:
                json.dump({"api": best[0], "ts": time.time()}, f)
            print(f"[CACHE ROUTER] ✅ Fastest API cached: {best[0]} ({best[2]}s)")
            return best[0]
        else:
            print("[CACHE ROUTER] ⚠️ No valid 200 responses — fallback random")
            return random.choice(list(API_POOL.keys()))


def get_cached_api(ttl=600):
    """Return cached API if recent; otherwise trigger async refresh."""
    if CACHE_FILE.exists():
        try:
            data = json.loads(CACHE_FILE.read_text())
            if time.time() - data["ts"] < ttl:
                print(f"[CACHE ROUTER] ♻️ Using cached API: {data['api']}")
                return data["api"]
        except Exception:
            pass
    print("[CACHE ROUTER] 🔄 Cache expired — refreshing async...")
    return asyncio.run(fetch_all())
