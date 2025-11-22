"""
fetch_unified.py — Phase-90 Rebuild
-----------------------------------
Unified data fetcher that:
 • Automatically detects stock vs crypto
 • Builds full OHLCV DataFrame (not single row)
 • Calculates technical indicators (RSI, MACD, MA)
 • Generates sparkline + volatility + rate-of-change
 • Feeds feature-ready structure to Ranking Engine & Agents
 • Wrapped with GuardianV3 for total crash immunity
"""

import requests
import pandas as pd
import numpy as np
import time

from astra_modules.api_keys import (
    FINNHUB_API_KEY,
    TWELVEDATA_API_KEY,
    MORALIS_API_KEY,
    ALPHA_VANTAGE_API_KEY,
)

from astra_modules.guardian.guardian_v3 import guardian


# ================================================================
# HELPERS
# ================================================================

def _is_crypto(symbol: str):
    if symbol is None:
        return False
    sym = symbol.upper()
    crypto_list = ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "USDT", "USDC"]
    return sym in crypto_list or len(sym) > 4


# ================================================================
# PHASE-90 TECHNICAL INDICATORS
# ================================================================

def compute_rsi(series, period=14):
    try:
        delta = series.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / loss
        return 100 - (100 / (1 + rs))
    except:
        return pd.Series([50] * len(series))

def compute_macd(series):
    try:
        ema12 = series.ewm(span=12).mean()
        ema26 = series.ewm(span=26).mean()
        macd = ema12 - ema26
        signal = macd.ewm(span=9).mean()
        return macd, signal
    except:
        return pd.Series([0]), pd.Series([0])


# ================================================================
# STOCK FETCHERS (MULTI-API)
# ================================================================

def _fetch_stock_ohlcv_finnhub(symbol, days):
    try:
        now = int(time.time())
        start = now - days * 86400
        url = (
            f"https://finnhub.io/api/v1/stock/candle"
            f"?symbol={symbol}&resolution=D&from={start}&to={now}&token={FINNHUB_API_KEY}"
        )
        r = requests.get(url, timeout=10).json()
        if r.get("s") != "ok":
            return pd.DataFrame()

        df = pd.DataFrame({
            "date": pd.to_datetime(r["t"], unit="s"),
            "open": r["o"],
            "high": r["h"],
            "low": r["l"],
            "close": r["c"],
            "volume": r["v"]
        })
        df["symbol"] = symbol
        return df
    except:
        return pd.DataFrame()


def _fetch_stock_ohlcv_twelvedata(symbol, days):
    try:
        url = (
            f"https://api.twelvedata.com/time_series?"
            f"symbol={symbol}&interval=1day&apikey={TWELVEDATA_API_KEY}"
            f"&outputsize={days}"
        )
        r = requests.get(url, timeout=10).json()
        values = r.get("values", [])
        df = pd.DataFrame(values)
        if df.empty:
            return df
        df = df.rename(columns={"datetime": "date"})
        df["date"] = pd.to_datetime(df["date"])
        df = df[["date", "open", "high", "low", "close", "volume"]].astype(float)
        df["symbol"] = symbol
        return df
    except:
        return pd.DataFrame()


# ================================================================
# CRYPTO FETCHERS
# ================================================================

def _fetch_crypto_coingecko(symbol, days):
    try:
        url = (
            "https://api.coingecko.com/api/v3/coins/"
            f"{symbol.lower()}/market_chart?vs_currency=usd&days={days}"
        )
        r = requests.get(url, timeout=10).json()
        prices = r.get("prices", [])
        if not prices:
            return pd.DataFrame()

        df = pd.DataFrame(prices, columns=["timestamp", "price"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        df["close"] = df["price"]
        df["open"] = df["close"].shift(1).fillna(df["close"])
        df["high"] = df["close"]
        df["low"] = df["close"]
        df["volume"] = 0
        df["symbol"] = symbol.upper()
        return df[["date", "open", "high", "low", "close", "volume", "symbol"]]
    except:
        return pd.DataFrame()


# ================================================================
# MASTER FETCH (PHASE-90)
# ================================================================

def fetch_unified(symbol, lookback=90):
    """
    Returns a full Phase-90 enriched DataFrame:
        - date, ohlcv
        - rsi, macd, macd_signal
        - sparkline list
        - volatility
        - price_change
    """

    df = pd.DataFrame()

    try:
        if _is_crypto(symbol):
            df = _fetch_crypto_coingecko(symbol, lookback)
        else:
            df = _fetch_stock_ohlcv_finnhub(symbol, lookback)
            if df.empty:
                df = _fetch_stock_ohlcv_twelvedata(symbol, lookback)
    except:
        df = pd.DataFrame()

    # Guardian validation
    df = guardian.validate_dataframe(df, required_columns=["date", "close"])

    if df.empty:
        return df

    # Sort chronologically
    df = df.sort_values("date").reset_index(drop=True)

    # ============================================================
    # PHASE-90 ENRICHMENT
    # ============================================================

    closes = df["close"].astype(float)

    # RSI
    df["rsi"] = compute_rsi(closes).fillna(50)

    # MACD + Signal
    macd, signal = compute_macd(closes)
    df["macd"] = macd
    df["macd_signal"] = signal

    # Moving averages
    df["ma_fast"] = closes.ewm(span=10).mean()
    df["ma_slow"] = closes.ewm(span=30).mean()

    # Sparkline data (last 30 closes)
    df["sparkline"] = [closes.tail(30).tolist()] * len(df)

    # Volatility
    df["volatility"] = closes.pct_change().rolling(10).std().fillna(0)

    # Price Change (Momentum feature)
    if len(closes) > 10:
        df["price_change"] = (closes - closes.shift(10)) / closes.shift(10)
    else:
        df["price_change"] = 0

    return df
