"""
Astra 7.0 - DataFrame Cleaner (SAFE VERSION)
--------------------------------------------
Prevents accidental numeric → string conversion.
Only strips whitespace on true text columns.
"""

import pandas as pd

NUMERIC_COLS = {"open", "high", "low", "close", "volume"}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip column names and force lowercase."""
    df.columns = [str(c).strip().lower() for c in df.columns]
    return df


def drop_missing(df: pd.DataFrame, col: str) -> pd.DataFrame:
    """Drop rows where a key column is missing."""
    if col in df.columns:
        df = df.dropna(subset=[col])
    return df


def strip_whitespace(df: pd.DataFrame) -> pd.DataFrame:
    """
    ONLY strip whitespace from true text columns.
    Never touch numeric or OHLCV columns.
    """
    for col in df.columns:
        if col not in NUMERIC_COLS:
            if df[col].dtype == object:
                df[col] = df[col].astype(str).str.strip()
    return df
