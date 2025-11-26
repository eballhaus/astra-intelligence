# ===============================================================
# Astra 7.0 — Clean Price DataFrame Utility
# Ensures all OHLCV data is numeric and stable for indicators.
# Prevents RSI/EMA/MACD crashes from bad API formatting.
# ===============================================================

import pandas as pd
import numpy as np


REQUIRED_COLS = ["open", "high", "low", "close", "volume"]


def ensure_required_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Adds missing OHLCV columns with NaN values."""
    for col in REQUIRED_COLS:
        if col not in df.columns:
            df[col] = np.nan
    return df


def force_numeric(df: pd.DataFrame) -> pd.DataFrame:
    """Converts all OHLCV columns to numeric, coercing errors."""
    for col in REQUIRED_COLS:
        df[col] = (
            df[col]
            .astype(str)
            .str.replace(",", "")
            .str.replace("$", "")
            .str.replace("None", "")
            .replace(["nan", ""], np.nan)
        )
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def drop_invalid_rows(df: pd.DataFrame) -> pd.DataFrame:
    """Drops rows missing OHLC or volume."""
    return df.dropna(subset=["open", "high", "low", "close"], how="any")


def sort_and_index(df: pd.DataFrame) -> pd.DataFrame:
    """Sort chronologically and set index to datetime."""
    # Try to find a date column:
    date_cols = [c for c in df.columns if "date" in c.lower() or "time" in c.lower()]
    if date_cols:
        col = date_cols[0]
        df[col] = pd.to_datetime(df[col], errors="coerce")
        df = df.dropna(subset=[col])
        df = df.sort_values(col)
        df = df.set_index(col)
    else:
        df = df.sort_index()

    return df


def clean_price_df(df: pd.DataFrame) -> pd.DataFrame:
    """
    Master cleaner:
      • Ensures OHLCV columns
      • Forces numeric
      • Removes broken rows
      • Sorts and indexes
    """

    if df is None or len(df) == 0:
        return pd.DataFrame(columns=REQUIRED_COLS)

    df = df.copy()

    df = ensure_required_columns(df)
    df = force_numeric(df)
    df = drop_invalid_rows(df)
    df = sort_and_index(df)

    return df
