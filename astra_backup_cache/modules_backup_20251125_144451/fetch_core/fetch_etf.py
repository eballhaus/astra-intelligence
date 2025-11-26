"""
Astra 7.0 - ETF Data Fetcher (Phase 45)
---------------------------------------
Fallback order:
    1. Alpha Vantage
    2. FMP
    3. EODHD
"""

import requests
import pandas as pd
from astra_modules.api_keys import (
    ALPHA_VANTAGE_API_KEY,
    FMP_API_KEY,
    EODHD_API_KEY
)
from astra_modules.utils.safe_df import safe_df
from astra_modules.utils.safe_api_wrapper import safe_api_call


def _convert(records):
    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)

    df.rename(columns={
        "date": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp"
    }, inplace=True)

    if "timestamp" in df:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

    for col in ["open", "high", "low", "close", "volume"]:
        if col in df:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.dropna(subset=["timestamp"])
    df = df.sort_values("timestamp").reset_index(drop=True)

    return df


# -------------------------------------------------------
# Alpha Vantage
# -------------------------------------------------------
def fetch_alpha_vantage_etf(symbol, interval="60min"):
    if not ALPHA_VANTAGE_API_KEY:
        return pd.DataFrame()

    url = (
        f"https://www.alphavantage.co/query?"
        f"function=TIME_SERIES_INTRADAY&symbol={symbol}&interval={interval}"
        f"&outputsize=full&apikey={ALPHA_VANTAGE_API_KEY}"
    )

    def run():
        r = safe_api_call(url)
        if not r:
            return pd.DataFrame()

        key = f"Time Series ({interval})"
        if key not in r:
            return pd.DataFrame()

        rows = []
        for t, v in r[key].items():
            rows.append({
                "timestamp": t,
                "open": v.get("1. open"),
                "high": v.get("2. high"),
                "low": v.get("3. low"),
                "close": v.get("4. close"),
                "volume": v.get("5. volume"),
            })

        return _convert(rows)

    return run()


# -------------------------------------------------------
# FMP
# -------------------------------------------------------
def fetch_fmp_etf(symbol, interval="1hour"):
    if not FMP_API_KEY:
        return pd.DataFrame()

    url = (
        f"https://financialmodelingprep.com/api/v3/historical-chart/"
        f"{interval}/{symbol}?apikey={FMP_API_KEY}"
    )

    def run():
        r = safe_api_call(url)
        return _convert(r or [])

    return run()


# -------------------------------------------------------
# EODHD
# -------------------------------------------------------
def fetch_eodhd_etf(symbol, interval="1h"):
    if not EODHD_API_KEY:
        return pd.DataFrame()

    url = (
        f"https://eodhd.com/api/intraday/{symbol}?"
        f"interval={interval}&api_token={EODHD_API_KEY}&fmt=json"
    )

    def run():
        r = safe_api_call(url)
        return _convert(r or [])

    return run()


# -------------------------------------------------------
# Unified ETF Fetch
# -------------------------------------------------------
def fetch_etf(symbol, interval="1h"):
    for provider in [
        fetch_alpha_vantage_etf,
        fetch_fmp_etf,
        fetch_eodhd_etf
    ]:
        df = provider(symbol, interval)
        if df is not None and not df.empty:
            return safe_df(df)

    return pd.DataFrame()
