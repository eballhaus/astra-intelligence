import asyncio
import aiohttp
import random
import time

from astra_dashboard.fetch_core.api_router import API_POOL


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
            print(f"[ASYNC ROUTER] ✅ Fastest API: {best[0]} ({best[2]}s)")
            return best[0]
        else:
            print("[ASYNC ROUTER] ⚠️ No 200 responses — fallback to random")
            return random.choice(list(API_POOL.keys()))
