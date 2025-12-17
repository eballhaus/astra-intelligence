import asyncio, os, httpx, pandas as pd
from datetime import datetime, timezone
from typing import Optional
from core.guardian.guardian_v7 import GuardianV7

guardian = GuardianV7()
CACHE_DIR = '/tmp/astra_cache'
os.makedirs(CACHE_DIR, exist_ok=True)

async def fetch_symbol(symbol: str) -> pd.DataFrame:
    try:
        guardian.info(f'Fetching data for {symbol}')
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f'https://api.astra-intelligence.ai/data/{symbol}')
            if r.status_code != 200:
                guardian.warning(f'{symbol} API returned {r.status_code}')
                return pd.DataFrame()
            df = pd.DataFrame(r.json().get('data', []))
            return df
    except Exception as e:
        guardian.error(f'Failed to fetch {symbol}: {e}')
        return pd.DataFrame()

def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    try:
        stocks = asyncio.run(fetch_symbol('SPY'))
        cryptos = asyncio.run(fetch_symbol('BTC-USD'))

        if stocks is None or stocks.empty:
            guardian.warning('Stocks data unavailable; substituting mock data.')
            stocks = pd.DataFrame({
                'symbol': ['AAPL','TSLA','NVDA','MSFT','AMZN','GOOG'],
                'price': [195,256,467,423,173,142]
            })

        if cryptos is None or cryptos.empty:
            guardian.warning('Crypto data unavailable; substituting mock data.')
            cryptos = pd.DataFrame({
                'symbol': ['BTC','ETH','SOL','XRP','ADA','DOGE'],
                'price': [47200,2450,105,0.65,0.54,0.12]
            })

        guardian.info('✅ Data load complete')
        return stocks, cryptos
    except Exception as e:
        guardian.error(f'load_data failed: {e}')
        return pd.DataFrame(), pd.DataFrame()
