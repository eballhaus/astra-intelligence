import asyncio
import aiohttp
from fetch_core.fetch_stock import fetch_stock
from fetch_core.fetch_crypto import fetch_crypto
from fetch_core.fetch_etf import fetch_etf


async def fetch_all():
    async with aiohttp.ClientSession() as session:
        tasks = [
            asyncio.create_task(fetch_stock(session)),
            asyncio.create_task(fetch_crypto(session)),
            asyncio.create_task(fetch_etf(session)),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return results


if __name__ == "__main__":
    asyncio.run(fetch_all())
