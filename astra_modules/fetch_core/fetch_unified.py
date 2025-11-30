"""
fetch_unified.py — Phase 108 Stable
Unified data fetcher with Guardian validation and mock fallback.
"""

import os
import requests
import pandas as pd
from datetime import datetime, timedelta

from astra_modules.api_keys import FINNHUB_API_KEY, TWELVEDATA_API_KEY

# ──────────────────────────────────────────────
# Lazy Guardian Import
# ──────────────────────────────────────────────
_GUARDIAN_INSTANCE = None

def get_guardian_instance():
    """Safely load GuardianV6 once per session."""
    global _GUARDIAN_INSTANCE
    if _GUARDIAN_INSTANCE is None:
        from astra_modules.guardian.guardian_v6 import GuardianV6
        root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
        _GUARDIAN_INSTANCE = GuardianV6(root_dir)
    return _GUARDIAN_INSTANCE

# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────
def _is_crypto(symbol):
    if symbol is None:
        return False
    sym = symbol.upper()
    return sym in ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "BNB", "USDT", "USDC"] or len(sym) > 4

def compute_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = -delta.clip(upper=0).rolling(period).mean()
    rs = gain / (loss + 1e-9)
    return 100 - (100 / (1 + rs))

def compute_macd(series):
    ema12 = series.ewm(span=12).mean()
    ema26 = series.ewm(span=26).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9).mean()
    return macd, signal

# ──────────────────────────────────────────────
# Fallback Mock Generator
# ──────────────────────────────────────────────
def _generate_mock_data(symbol, lookback=90):
    """Generate realistic mock OHLCV data when APIs fail."""
    import numpy as np
    now = datetime.utcnow()
    dates = [now - timedelta(days=i) for i in range(lookback)][::-1]
    prices = np.linspace(100, 110 + (hash(symbol) % 50), lookback) + np.random.normal(0, 2, lookback)
    df = pd.DataFrame({
        "date": dates,
        "open": prices * 0.99,
        "high": prices * 1.01,
        "low": prices * 0.98,
        "close": prices,
        "volume": np.random.randint(1000, 5000, size=lookback)
    })
    return df

# ──────────────────────────────────────────────
# Fetch Logic
# ──────────────────────────────────────────────
def _fetch_stock(symbol, lookback=90):
    try:
        url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={FINNHUB_API_KEY}"
        data = requests.get(url, timeout=5).json()
        if "c" not in data:
            raise ValueError("Invalid response from Finnhub.")
        df = pd.DataFrame([{
            "date": datetime.utcnow(),
            "open": data.get("o", 0),
            "high": data.get("h", 0),
            "low": data.get("l", 0),
            "close": data.get("c", 0),
            "volume": data.get("v", 0),
        }])
        return df
    except Exception:
        return pd.DataFrame()

def _fetch_crypto(symbol, lookback=90):
    try:
        sym = symbol.split("/")[0].lower()
        url = f"https://api.coingecko.com/api/v3/coins/{sym}/market_chart?vs_currency=usd&days={lookback}"
        data = requests.get(url, timeout=5).json()
        prices = data.get("prices", [])
        if not prices:
            return pd.DataFrame()
        df = pd.DataFrame(prices, columns=["timestamp", "close"])
        df["date"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception:
        return pd.DataFrame()

# ──────────────────────────────────────────────
# Main Unified Fetch
# ──────────────────────────────────────────────
def fetch_unified(symbol, lookback=90):
    guardian = get_guardian_instance()

    df = _fetch_crypto(symbol, lookback) if _is_crypto(symbol) else _fetch_stock(symbol, lookback)
    if df.empty:
        df = _generate_mock_data(symbol, lookback)

    df = guardian.validate_dataframe(df, required_columns=["date", "close"])
    if df.empty:
        return df

    df = df.sort_values("date").reset_index(drop=True)
    closes = df["close"].astype(float)

    df["rsi"] = compute_rsi(closes).fillna(50)
    macd, signal = compute_macd(closes)
    df["macd"] = macd
    df["macd_signal"] = signal
    df["ma_fast"] = closes.ewm(span=10).mean()
    df["ma_slow"] = closes.ewm(span=30).mean()
    df["sparkline"] = [closes.tail(30).tolist()] * len(df)
    df["volatility"] = closes.pct_change().rolling(10).std().fillna(0)
    df["price_change"] = (closes - closes.shift(10)) / closes.shift(10)

    return df
