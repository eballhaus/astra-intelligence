"""
Astra Intelligence — Dashboard Data Layer (v3)
----------------------------------------------
Provides clean, validated, and Guardian-safe access to market data
for all dashboard components (charts, cards, summaries, etc.)
"""

import pandas as pd

from astra_core.fetch_core import fetch_unified
from astra_core.guardian import guardian_log
from astra_core.guardian.schema_validator import validate_and_normalize

guardian = guardian_log()


# ============================================================
# 🧩 LOAD DATA (Restored Wrapper)
# ============================================================


def load_data(symbol: str) -> pd.DataFrame:
    """
    Unified data loader for dashboard.
    Fetches from Astra's unified data source, validates schema,
    and returns a DataFrame ready for visualization.
    """
    try:
        raw = fetch_unified.get_symbol_data(symbol)
        df = validate_and_normalize(raw, "fetch_unified")

        # Simulate basic OHLCV structure for charts if not present
        if "timestamp" not in df.columns:
            df["timestamp"] = pd.date_range(
                end=pd.Timestamp.now(), periods=len(df))
        if "open" not in df.columns:
            df["open"] = df["price"]
        if "high" not in df.columns:
            df["high"] = df["price"]
        if "low" not in df.columns:
            df["low"] = df["price"]
        if "close" not in df.columns:
            df["close"] = df["price"]
        if "volume" not in df.columns:
            df["volume"] = 1000.0

        guardian.log(f"[DashboardData] Loaded {symbol} ({len(df)} rows).")
        return df

    except Exception as e:
        guardian.log(
            f"[DashboardData] 🚨 Failed to load data for {symbol}: {e}")
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )


# ============================================================
# 🧠 HIGHER-LEVEL ACCESSORS (OPTIONAL)
# ============================================================


def get_price_series(symbol: str) -> pd.Series:
    """Return just the closing price series."""
    df = load_data(symbol)
    if "close" in df.columns:
        return df["close"]
    return pd.Series(dtype=float)


def get_summary(symbol: str) -> dict:
    """Generate summary metrics for the symbol."""
    df = load_data(symbol)
    if df.empty:
        return {"symbol": symbol, "price": None, "change_pct": None}

    latest = df.iloc[-1]
    change_pct = 0
    if "close" in df.columns and len(df["close"]) > 1:
        change_pct = (df["close"].iloc[-1] / df["close"].iloc[-2] - 1) * 100

    return {
        "symbol": symbol,
        "price": float(latest.get("close", 0)),
        "change_pct": round(change_pct, 2),
        "rows": len(df),
    }


if __name__ == "__main__":
    guardian.log("🧩 Dashboard Data self-test starting...")
    print(load_data("BTC/USD").head())


def load_data(symbol):
    """Pull live market data via fetch_unified"""
    return fetch_unified(symbol)


def load_data(symbol):
    return fetch_unified(symbol)


# load_data wrapper for dashboard


def load_data(symbol):
    return fetch_unified(symbol)
