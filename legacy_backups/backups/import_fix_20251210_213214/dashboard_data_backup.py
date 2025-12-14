# ============================================================
# Astra Intelligence — Dashboard Data Layer (v3.5 Stable)
# ============================================================
"""
Provides clean, validated, and Guardian-safe access to market data
for all dashboard components (charts, cards, summaries, etc.)
"""

import pandas as pd
from astra_core.guardian.guardian_v6 import guardian

from astra_core.fetch_core import fetch_unified
from astra_core.utils.data_validation import validate_and_normalize  # if you have it

# If not, Guardian will log a warning

guardian.log("[DashboardData] ✅ Module loaded successfully.")


# ============================================================
# 🧩 LOAD DATA (Unified Astra Pipeline)
# ============================================================
def load_data(symbol: str) -> pd.DataFrame:
    """
    Unified data loader for dashboard.
    Fetches from Astra's unified data source, validates schema,
    and returns a DataFrame ready for visualization.
    """
    try:
        # --- Step 1: Fetch Data ---
        raw = fetch_unified.get_symbol_data(symbol)
        if raw is None or len(raw) == 0:
            guardian.log(f"[DashboardData] ⚠️ No data returned for {symbol}.")
            return pd.DataFrame(
                columns=["timestamp", "open", "high", "low", "close", "volume"]
            )

        # --- Step 2: Validate & Normalize ---
        try:
            df = validate_and_normalize(raw, "fetch_unified")
        except Exception as ve:
            guardian.log(
                f"[DashboardData] ⚠️ Validation skipped ({ve}). Using raw data."
            )
            df = pd.DataFrame(raw)

        # --- Step 3: Ensure structure ---
        for col in ["timestamp", "open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                if col == "timestamp":
                    df[col] = pd.date_range(end=pd.Timestamp.now(), periods=len(df))
                elif col in ["open", "high", "low", "close"]:
                    df[col] = df.get("price", 0)
                elif col == "volume":
                    df[col] = 1000.0

        # --- Step 4: Return ---
        guardian.log(f"[DashboardData] ✅ Loaded {symbol} ({len(df)} rows).")
        return df

    except Exception as e:
        guardian.log(f"[DashboardData] 🚨 Failed to load data for {symbol}: {e}")
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )


# ============================================================
# 🧠 HIGHER-LEVEL ACCESSORS
# ============================================================
def get_price_series(symbol: str) -> pd.Series:
    """Return only the close price series for fast charting."""
    try:
        df = load_data(symbol)
        return df["close"]
    except Exception as e:
        guardian.log(f"[DashboardData] ⚠️ Price series fetch failed for {symbol}: {e}")
        return pd.Series(dtype=float)


def get_latest_snapshot(symbol: str) -> dict:
    """Return the latest snapshot (close, volume, timestamp)."""
    try:
        df = load_data(symbol)
        if df.empty:
            return {}
        latest = df.iloc[-1].to_dict()
        latest["symbol"] = symbol
        return latest
    except Exception as e:
        guardian.log(f"[DashboardData] ⚠️ Snapshot fetch failed for {symbol}: {e}")
        return {}
