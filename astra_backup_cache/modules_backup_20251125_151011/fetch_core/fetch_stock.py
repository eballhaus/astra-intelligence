"""
Astra 7.0 - Unified Stock Fetcher (Phase 45)
--------------------------------------------
Priority:
    1. Alpha Vantage (daily adjusted)
    2. Financial Modeling Prep (historical)
    3. TwelveData (daily)
"""

import pandas as pd
from datetime import datetime

from astra_modules.api_keys import (
    ALPHA_VANTAGE_API_KEY,
    FMP_API_KEY,
    TWELVE_DATA_API_KEY
)

from astra_modules.utils.safe_df import safe_df
from astra_modules.utils.safe_api_wrapper import safe_api_call
from astra_modules.utils.caching import cache_set


# ---------------------------------------------------------
# Alpha Vantage
# ---------------------------------------------------------
def fetch_alpha(symbol):
    url = (
        f"https://www.alphavantage.co/query?"
        f"function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}"
        f"&apikey={ALPHA_VANTAGE_API_KEY}"
    )

    data = safe_api_call(url)
    if not data or "Time Series (Daily)" not in data:
        return None

    df = pd.DataFrame.from_dict(data["Time Series (Daily)"], orient="index")
    df.index = pd.to_datetime(df.index)
    df = df.sort_index()

    df = df.rename(columns={
        "1. open": "open",
        "2. high": "high",
        "3. low": "low",
        "4. close": "close",
        "6. volume": "volume",
    })

    return safe_df(df)


# ---------------------------------------------------------
# Financial Modeling Prep
# ---------------------------------------------------------
def fetch_fmp(symbol):
    url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?apikey={FMP_API_KEY}"

    data = safe_api_call(url)
    if not data or "historical" not in data:
        return None

    df = pd.DataFrame(data["historical"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    return safe_df(df)


# ---------------------------------------------------------
# TwelveData
# ---------------------------------------------------------
def fetch_twelve(symbol):
    url = (
        f"https://api.twelvedata.com/time_series?"
        f"symbol={symbol}&interval=1day&outputsize=5000&apikey={TWELVE_DATA_API_KEY}"
    )

    data = safe_api_call(url)
    if not data or "values" not in data:
        return None

    df = pd.DataFrame(data["values"])
    df["datetime"] = pd.to_datetime(df["datetime"])
    df = df.set_index("datetime").sort_index()

    return safe_df(df)


# ---------------------------------------------------------
# Unified Stock Fetch
# ---------------------------------------------------------
def fetch_stock(symbol, interval="1h"):
    for provider in [fetch_alpha, fetch_fmp, fetch_twelve]:
        df = provider(symbol)
        if df is not None and not df.empty:
            cache_set(symbol, df)
            return df

    return pd.DataFrame()
