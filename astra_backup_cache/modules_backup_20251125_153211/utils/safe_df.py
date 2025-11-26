"""
safe_df.py — Phase-50 DataFrame Safety System
Ensures unified OHLC structure across ALL providers (Finnhub, TwelveData,
EODHD, Moralis, CoinGecko). Prevents crashes in Ranking Engine, SmartScan,
HybridScan, and Advanced Chart.
"""

import pandas as pd
from astra_modules.guardian.guardian_v3 import guardian


# =====================================================================
# MAIN SAFETY WRAPPER
# =====================================================================
def safe_price_df(df, symbol="UNKNOWN"):
    """
    Ensures the returned DataFrame is ALWAYS valid, clean, and safe.
    - Returns empty but valid DF if input is None
    - Forces required columns: datetime, open, high, low, close, volume
    - Removes duplicates
    - Removes invalid rows
    - Sorts ascending
    """

    # ------------------------------------------------------------
    # NULL INPUT → RETURN EMPTY SAFE DF
    # ------------------------------------------------------------
    if df is None or len(df) == 0:
        return _empty_template()

    try:
        # Make sure it's a DataFrame
        df = pd.DataFrame(df)

        # Required columns
        required_cols = ["datetime", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = 0

        # Convert datetimes
        try:
            df["datetime"] = pd.to_datetime(df["datetime"], errors="coerce")
        except:
            df["datetime"] = pd.to_datetime("now")

        # Drop invalid datetime rows
        df = df.dropna(subset=["datetime"])

        # Sort
        df = df.sort_values("datetime")

        # Drop duplicates
        df = df.drop_duplicates(subset=["datetime"])

        # Final guardian pass
        df = guardian.ensure_price_df(df)

        return df

    except Exception as e:
        guardian.log_error(f"[safe_price_df] Fatal DF error for {symbol}: {e}")
        return _empty_template()


# =====================================================================
# EMPTY TEMPLATE (Used when APIs fail)
# =====================================================================
def _empty_template():
    """Return a safe empty dataframe so nothing breaks."""
    return pd.DataFrame({
        "datetime": pd.to_datetime([]),
        "open": [],
        "high": [],
        "low": [],
        "close": [],
        "volume": [],
    })
