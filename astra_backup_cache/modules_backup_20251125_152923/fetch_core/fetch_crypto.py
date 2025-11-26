"""
Astra 7.0 - Crypto Fetcher (Phase 45)
------------------------------------
Fallback:
    1. Moralis
    2. CoinGecko
"""

import requests
import pandas as pd
from astra_modules.api_keys import MORALIS_API_KEY
from astra_modules.utils.safe_df import safe_df
from astra_modules.utils.safe_api_wrapper import safe_api_call


def _to_df_ohlcv(records):
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df.rename(columns={
        "t": "timestamp",
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume"
    }, inplace=True)

    if "timestamp" in df:
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", errors="coerce")

    for c in ["open", "high", "low", "close", "volume"]:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)
    return df


# -------------------------------------------------------
# Moralis
# -------------------------------------------------------
def fetch_moralis(symbol, interval="1h"):
    if not MORALIS_API_KEY:
        return pd.DataFrame()

    token = symbol.lower()
    res_map = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "D"
    }
    resolution = res_map.get(interval, "60")

    url = (
        f"https://deep-index.moralis.io/api/v2/market-data/ohlcv/"
        f"{token}/usd?resolution={resolution}&limit=5000"
    )

    headers = {"X-API-Key": MORALIS_API_KEY}

    r = safe_api_call(url)
    if not r or "result" not in r:
        return pd.DataFrame()

    records = r["result"].get("data", [])
    return _to_df_ohlcv(records)


# -------------------------------------------------------
# CoinGecko (backup)
# -------------------------------------------------------
def fetch_coingecko(symbol, interval="1h"):
    token = symbol.lower()

    days_map = {
        "1m": 1,
        "5m": 1,
        "15m": 1,
        "30m": 1,
        "1h": 2,
        "4h": 4,
        "1d": 7
    }
    days = days_map.get(interval, 2)

    url = f"https://api.coingecko.com/api/v3/coins/{token}/ohlc?vs_currency=usd&days={days}"

    r = safe_api_call(url)
    if not isinstance(r, list):
        return pd.DataFrame()

    rows = []
    for row in r:
        if len(row) == 5:
            rows.append({
                "timestamp": row[0],
                "open": row[1],
                "high": row[2],
                "low": row[3],
                "close": row[4],
                "volume": None
            })

    return _to_df_ohlcv(rows)


# -------------------------------------------------------
# Unified
# -------------------------------------------------------
def fetch_crypto(symbol, interval="1h"):
    for provider in [fetch_moralis, fetch_coingecko]:
        df = provider(symbol, interval)
        if df is not None and not df.empty:
            return safe_df(df)

    return pd.DataFrame()
