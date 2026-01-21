import os
from datetime import datetime, timedelta

import pandas as pd
import requests

from astra_modules.guardian.guardian_v7 import Guardian
from astra_modules.utils.df_cleaner import normalize_columns, strip_whitespace
from astra_modules.utils.safe_api_wrapper import safe_api_call

g = Guardian()

"""
Astra 7.2 — Universal FetchCore (Auto-Rotating, Env-Based)
---------------------------------------------------------
Upgrades:
• Loads all API keys dynamically from environment
• Unified fallback rotation (auto-switch on failure)
• Improved EODHD/Finnhub handling
• Compatible with Guardian Health Monitor
"""


# ===============================================================
# ENVIRONMENT-LOADED KEYS
# ===============================================================
FINNHUB_KEY = os.getenv("FINNHUB_KEY")
FMP_KEY = os.getenv("FMP_KEY")
AV_KEY = os.getenv("ALPHAVANTAGE_KEY") or os.getenv("AV_KEY")
TD_KEY = os.getenv("TWELVEDATA_KEY")
EOD_KEY = os.getenv("EODHD_KEY") or os.getenv("EOD_KEY")
MORALIS_KEY = os.getenv("MORALIS_KEY")


# ===============================================================
# CLEANING / UTILITIES
# ===============================================================
def clean_ohlcv(df: pd.DataFrame):
    if df is None or df.empty:
        return None
    df = normalize_columns(df)
    df = strip_whitespace(df)
    rename_map = {"o": "open", "h": "high",
                  "l": "low", "c": "close", "v": "volume"}
    df.rename(columns=rename_map, inplace=True)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(
                df[col]
                .astype(str)
                .str.replace(",", "")
                .str.replace("$", "")
                .str.strip(),
                errors="coerce",
            )
    return df.dropna(subset=["close"])


def limit_to_lookback(df, lookback_days):
    if df is None or df.empty:
        return None
    cutoff = datetime.now() - timedelta(days=lookback_days)
    return df[df.index >= cutoff] if hasattr(df, "index") else df


# ===============================================================
# INDIVIDUAL FETCH FUNCTIONS
# ===============================================================
def fetch_finnhub(symbol, lookback_days):
    if not FINNHUB_KEY:
        return None
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": symbol, "resolution": "D", "token": FINNHUB_KEY}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    if data.get("s") != "ok":
        return None
    df = pd.DataFrame(
        {
            "open": data["o"],
            "high": data["h"],
            "low": data["l"],
            "close": data["c"],
            "volume": data["v"],
        },
        index=pd.to_datetime(data["t"], unit="s"),
    )
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


def fetch_fmp(symbol, lookback_days):
    if not FMP_KEY:
        return None
    params = {"apikey": FMP_KEY, "timeseries": lookback_days}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    if "historical" not in data:
        return None
    df = pd.DataFrame(data["historical"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


def fetch_alpha_vantage(symbol, lookback_days):
    if not AV_KEY:
        return None
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY_ADJUSTED",
        "symbol": symbol,
        "apikey": AV_KEY,
    }
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    ts = data.get("Time Series (Daily)") or data.get(
        "Time Series (Daily Adjusted)")
    if ts is None:
        return None
    df = pd.DataFrame(ts).T
    df.index = pd.to_datetime(df.index)
    df = df.rename(columns=lambda c: c.lower().split(".")[-1])
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


def fetch_twelvedata(symbol, lookback_days):
    if not TD_KEY:
        return None
    url = "https://api.twelvedata.com/time_series"
    params = {"symbol": symbol, "interval": "1h",
              "apikey": TD_KEY, "outputsize": 500}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    if "values" not in data:
        return None
    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


def fetch_eodhd(symbol, lookback_days):
    if not EOD_KEY:
        return None
    url = f"https://eodhd.com/api/eod/{symbol}"
    params = {"api_token": EOD_KEY, "fmt": "json"}
    r = requests.get(url, params=params, timeout=5)
    data = r.json()
    if not isinstance(data, list):
        return None
    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


def fetch_moralis(symbol, lookback_days):
    if not MORALIS_KEY:
        return None
    url = "https://deep-index.moralis.io/api/v2.2/market-data/ohlcv"
    headers = {"X-API-Key": MORALIS_KEY, "accept": "application/json"}
    params = {"symbol": f"{symbol.lower()}/usd", "chain": "eth",
              "resolution": "1h"}
    r = requests.get(url, headers=headers, params=params, timeout=10)
    j = r.json()
    if "result" not in j:
        return None
    df = pd.DataFrame(j["result"])
    df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
    df.set_index("datetime", inplace=True)
    return limit_to_lookback(clean_ohlcv(df), lookback_days)


# ===============================================================
# UNIVERSAL AUTO-ROTATING FETCHER
# ===============================================================
def fetch_ohlcv(symbol: str, lookback_days: int):
    apis = [
        ("TwelveData", fetch_twelvedata),
        ("EODHD", fetch_eodhd),
        ("Finnhub", fetch_finnhub),
        ("AlphaVantage", fetch_alpha_vantage),
        ("FMP", fetch_fmp),
        ("Moralis", fetch_moralis),
    ]
    for name, api_func in apis:
        df = safe_api_call(lambda: api_func(symbol, lookback_days))
        if df is not None and not df.empty:
            print(
                f"[FetchCore] ✅ Data fetched from {name} ({symbol}) — {len(df)} rows."
            )
            return df
        else:
            print(f"[FetchCore] ⚠️ {name} returned no valid data.")
    print("[FetchCore] ❌ All sources failed.")
    return pd.DataFrame()
