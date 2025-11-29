# ──────────────────────────────────────────────
# Astra Intelligence — Multi-API Data Loader
# Phase-105 | AstraGlass Neural Interface
# ──────────────────────────────────────────────

import asyncio
import importlib.util
import logging
import os
from pathlib import Path

import aiohttp
import pandas as pd

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("AstraDashboardData")

# ──────────────────────────────────────────────
# Load API Keys from api_keys.py
# ──────────────────────────────────────────────
key_file = Path("/Users/ericballhaus/Desktop/astra-intelligence/api_keys.py")
if key_file.exists():
    spec = importlib.util.spec_from_file_location("astra_api_keys", key_file)
    keys = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(keys)
    os.environ["ALPHAVANTAGE_API_KEY"] = getattr(
        keys, "ALPHAVANTAGE_API_KEY", "")
    os.environ["FMP_API_KEY"] = getattr(keys, "FMP_API_KEY", "")
    os.environ["TWELVEDATA_API_KEY"] = getattr(keys, "TWELVEDATA_API_KEY", "")
    os.environ["FINNHUB_API_KEY"] = getattr(keys, "FINNHUB_API_KEY", "")
    os.environ["EODHD_API_KEY"] = getattr(keys, "EODHD_API_KEY", "")
    os.environ["MORALIS_API_KEY"] = getattr(keys, "MORALIS_API_KEY", "")
else:
    log.warning("⚠️ api_keys.py not found — API data may not load.")

# ──────────────────────────────────────────────
# Define all API key variables globally
# ──────────────────────────────────────────────
ALPHA_KEY = os.getenv("ALPHAVANTAGE_API_KEY")
FMP_KEY = os.getenv("FMP_API_KEY")
TD_KEY = os.getenv("TWELVEDATA_API_KEY")
FINN_KEY = os.getenv("FINNHUB_API_KEY")
EOD_KEY = os.getenv("EODHD_API_KEY")
MORALIS_KEY = os.getenv("MORALIS_API_KEY")

# ──────────────────────────────────────────────
# Default Dashboard Symbols
# ──────────────────────────────────────────────
TOP_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "META", "TSLA"]
TOP_CRYPTOS = ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA"]


# ──────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────
async def fetch_json(session, url, headers=None):
    """Fetch JSON safely from an endpoint."""
    try:
        async with session.get(url, headers=headers, timeout=8) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                log.warning(f"⚠️ {url} returned {resp.status}")
    except Exception as e:
        log.error(f"❌ Error fetching {url}: {e}")
    return None


def calc_change(current, prev):
    if not current or not prev or prev == 0:
        return 0.0
    return round(((current - prev) / prev) * 100, 2)


# ──────────────────────────────────────────────
# Stock & Crypto Loaders
# ──────────────────────────────────────────────
async def get_alpha_vantage(session, symbol):
    if not ALPHA_KEY:
        return None
    url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}&apikey={ALPHA_KEY}"
    data = await fetch_json(session, url)
    if not data or "Time Series (Daily)" not in data:
        return None
    ts = data["Time Series (Daily)"]
    dates = sorted(ts.keys())
    latest, prev = float(ts[dates[-1]]["4. close"]
                         ), float(ts[dates[-2]]["4. close"])
    return {
        "symbol": symbol,
        "price": latest,
        "change": calc_change(latest, prev),
        "source": "AlphaVantage",
    }


async def get_fmp(session, symbol):
    if not FMP_KEY:
        return None
    url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={FMP_KEY}"
    data = await fetch_json(session, url)
    if data and isinstance(data, list) and len(data) > 0:
        d = data[0]
        return {
            "symbol": symbol,
            "price": d.get("price"),
            "change": d.get("changesPercentage"),
            "source": "FMP",
        }
    return None


async def get_twelvedata(session, symbol):
    if not TD_KEY:
        return None
    url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TD_KEY}"
    data = await fetch_json(session, url)
    if data and "price" in data:
        return {
            "symbol": symbol,
            "price": float(data["price"]),
            "change": 0.0,
            "source": "TwelveData",
        }
    return None


async def get_moralis_crypto(session, symbol):
    if not MORALIS_KEY:
        return None
    url = f"https://deep-index.moralis.io/api/v2/market-data/price?pair={symbol.lower()}usdt"
    headers = {"X-API-Key": MORALIS_KEY}
    data = await fetch_json(session, url, headers=headers)
    if data and "usdPrice" in data:
        return {
            "symbol": symbol,
            "price": float(data["usdPrice"]),
            "change": 0.0,
            "source": "Moralis",
        }
    return None


# ──────────────────────────────────────────────
# Aggregator
# ──────────────────────────────────────────────
async def get_dashboard_data(symbol=None):
    """Main Astra dashboard data loader (async)."""

    async with aiohttp.ClientSession() as session:
        if symbol:
            # Detailed mode
            tasks = [get_fmp(session, symbol),
                     get_alpha_vantage(session, symbol)]
            results = [r for r in await asyncio.gather(*tasks) if r]
            return (
                results[0]
                if results
                else {"symbol": symbol, "price": None, "change": None}
            )

        # Dashboard overview
        stock_tasks = [get_fmp(session, s) for s in TOP_STOCKS]
        crypto_tasks = [get_moralis_crypto(session, c) for c in TOP_CRYPTOS]
        stocks = [r for r in await asyncio.gather(*stock_tasks) if r]
        cryptos = [r for r in await asyncio.gather(*crypto_tasks) if r]

        return {"stocks": stocks, "crypto": cryptos}


# ──────────────────────────────────────────────
# Sync wrapper for Streamlit
# ──────────────────────────────────────────────
def load_dashboard_data(symbol=None):
    """Streamlit-safe wrapper."""
    return asyncio.run(get_dashboard_data(symbol))


# ──────────────────────────────────────────────
# Self-test
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing Astra Data Engine (multi-API)...")
    data = load_dashboard_data()
    print(pd.DataFrame(data["stocks"]))
    print(pd.DataFrame(data["crypto"]))
