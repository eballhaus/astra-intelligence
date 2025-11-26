"""
Astra 7.0 — Universal Fetcher (FINAL BULLETPROOF VERSION)
---------------------------------------------------------
Now supports:
• fetch_ohlcv(symbol, lookback_days)
• Date filtering
• Full numeric sanitization
• Protection against malformed API responses
"""

import pandas as pd
import requests
from datetime import datetime, timedelta
from astra_modules.utils.safe_api_wrapper import safe_api_call
from astra_modules.utils.df_cleaner import normalize_columns, strip_whitespace

# ===============================================================
# API KEYS
# ===============================================================

FINNHUB_KEY = "d42ee5hr01qorleqvvb0d42ee5hr01qorleqvvbg"
FMP_KEY = "xbgYJPXsiwJ3coLczphQSBsghO7fTklM"
AV_KEY = "YJVYAJJSKKXF3ZQB"
TD_KEY = "452b5c89fc8747d4803ee6bda5f891b2"
EOD_KEY = "6904e7a2ced028.25933984"


# ===============================================================
# UNIVERSAL CLEANING
# ===============================================================

def clean_ohlcv(df: pd.DataFrame):
    """
    Fully cleans and standardizes OHLCV:
    - normalize column names
    - strip whitespace
    - enforce numeric float64 types
    - drop NaNs
    """
    if df is None or df.empty:
        return None

    df = normalize_columns(df)
    df = strip_whitespace(df)

    rename_map = {
        "o": "open",
        "h": "high",
        "l": "low",
        "c": "close",
        "v": "volume",
    }

    df.rename(columns=rename_map, inplace=True)

    # Force numeric conversion
    numeric_cols = ["open", "high", "low", "close", "volume"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = (
                df[col]
                .astype(str)
                .str.replace(",", "")
                .str.replace("$", "")
                .str.replace("None", "")
                .str.replace("nan", "")
                .str.strip()
            )
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Drop rows missing core values
    df = df.dropna(subset=["close"])

    return df


# ===============================================================
# DATE FILTER
# ===============================================================

def limit_to_lookback(df, lookback_days):
    """Returns only rows within lookback window."""
    if df is None or df.empty:
        return None

    cutoff = datetime.now() - timedelta(days=lookback_days)
    df = df[df.index >= cutoff]

    if df.empty:
        return None
    return df


# ===============================================================
# API FETCH FUNCTIONS
# ===============================================================

def fetch_finnhub(symbol, lookback_days):
    url = "https://finnhub.io/api/v1/stock/candle"
    params = {"symbol": symbol, "resolution": "D", "token": FINNHUB_KEY}

    r = requests.get(url, params=params, timeout=5)
    data = r.json()

    if data.get("s") != "ok":
        return None

    df = pd.DataFrame({
        "open": data["o"],
        "high": data["h"],
        "low": data["l"],
        "close": data["c"],
        "volume": data["v"],
        "timestamp": data["t"],
    })

    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="s")
    df.set_index("timestamp", inplace=True)

    df = clean_ohlcv(df)
    return limit_to_lookback(df, lookback_days)


def fetch_fmp(symbol, lookback_days):
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}"
    params = {"apikey": FMP_KEY}

    r = requests.get(url, params=params, timeout=5)
    data = r.json()

    if "historical" not in data:
        return None

    df = pd.DataFrame(data["historical"])
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)

    df = clean_ohlcv(df)
    return limit_to_lookback(df, lookback_days)


def fetch_alpha_vantage(symbol, lookback_days):
    url = "https://www.alphavantage.co/query"
    params = {
        "function": "TIME_SERIES_DAILY",
        "symbol": symbol,
        "apikey": AV_KEY,
    }

    r = requests.get(url, params=params, timeout=5)
    data = r.json()

    ts = data.get("Time Series (Daily)")
    if ts is None:
        return None

    df = pd.DataFrame(ts).T
    df.index = pd.to_datetime(df.index)
    df.columns = ["open", "high", "low", "close", "volume"]

    df = clean_ohlcv(df)
    return limit_to_lookback(df, lookback_days)


def fetch_twelvedata(symbol, lookback_days):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "1day",
        "apikey": TD_KEY,
        "outputsize": 500,
    }

    r = requests.get(url, params=params, timeout=5)
    data = r.json()

    if "values" not in data:
        return None

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df.set_index("datetime", inplace=True)

    df = clean_ohlcv(df)
    return limit_to_lookback(df, lookback_days)


def fetch_eodhd(symbol, lookback_days):
    url = f"https://eodhd.com/api/eod/{symbol}"
    params = {"api_token": EOD_KEY, "fmt": "json"}

    r = requests.get(url, params=params, timeout=5)
    data = r.json()

    df = pd.DataFrame(data)
    df["date"] = pd.to_datetime(df["date"])
    df.set_index("date", inplace=True)

    df = clean_ohlcv(df)
    return limit_to_lookback(df, lookback_days)


# ===============================================================
# UNIVERSAL FETCH FUNCTION — FINAL
# ===============================================================

def fetch_ohlcv(symbol: str, lookback_days: int):
    """
    Attempts all APIs in priority order.
    Returns the FIRST valid numeric OHLCV DataFrame.
    """

    apis = [
        fetch_finnhub,
        fetch_fmp,
        fetch_alpha_vantage,
        fetch_twelvedata,
        fetch_eodhd,
    ]

    for api in apis:
        df = safe_api_call(lambda: api(symbol, lookback_days))
        if df is not None and not df.empty:
            return df

    return None
