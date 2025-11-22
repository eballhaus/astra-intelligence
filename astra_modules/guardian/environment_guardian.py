"""
Environment Guardian 2.1
Fast, lightweight safety wrappers for Astra.
"""

import pandas as pd
import numpy as np
import importlib

# --------------------------------------------
# BASIC CLEANERS
# --------------------------------------------

def ensure_dataframe(obj):
    """Convert anything into a pandas DataFrame safely."""
    if isinstance(obj, pd.DataFrame):
        return obj.copy()
    if isinstance(obj, dict):
        return pd.DataFrame(obj)
    raise TypeError("Expected DataFrame or dict-like object.")

def ensure_numeric(series):
    """Ensure column is numeric, coercing errors to NaN."""
    return pd.to_numeric(series, errors="coerce")

def guard_pipeline_output(df):
    """Final sanity pass to remove infinities and impossible values."""
    df = df.replace([np.inf, -np.inf], np.nan)
    df = df.dropna(how="all")
    return df

# --------------------------------------------
# SAFE IMPORT WRAPPER (Prevents Crashes)
# --------------------------------------------

def safe_import(module_name: str):
    """
    Import a module — but never crash the dashboard if it fails.
    Returns None instead of raising ImportError.
    """
    try:
        return importlib.import_module(module_name)
    except Exception as e:
        print(f"[Guardian] Import failed: {module_name} — {e}")
        return None
