# =====================================================================
# learning_engine.py — Astra Phase-60 Learning Intelligence Core
# =====================================================================
# This module teaches Astra how to interpret the data stored
# in learning_store.py and automatically adjust prediction /
# ranking behavior over time.
#
# Key Features:
#   ✔ Rolling 90-day training window
#   ✔ Momentum + volatility learning
#   ✔ Dynamic buy_score weighting
#   ✔ Learn which hybrid signals predict success
#   ✔ Robust fallbacks if data missing
#   ✔ Guardian-safe numeric conversions
#   ✔ Ultra-fast training (vectorized Pandas)
#
# =====================================================================

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from astra_modules.learning.learning_store import load_records
from astra_modules.guardian.guardian_v3 import guardian


# =====================================================================
# GLOBAL DEFAULT WEIGHTS (Initial Seed)
# These evolve as Astra learns.
# =====================================================================
LEARNING_STATE = {
    "momentum_weight": 0.25,
    "volatility_weight": 0.15,
    "trend_weight": 0.20,
    "hybrid_weight": 0.20,
    "confidence_weight": 0.20,

    "last_trained": None,
    "samples_used": 0
}


# =====================================================================
# SAFE NORMALIZATION
# =====================================================================
def _safe_norm(series):
    if len(series) == 0:
        return series
    std = series.std()
    if std == 0 or pd.isna(std):
        return series * 0
    return (series - series.mean()) / std


# =====================================================================
# COMPUTE TRAINING LABELS
# Outcome = next-day return
# =====================================================================
def _compute_targets(df):
    df = df.sort_values("timestamp")
    df["next_close"] = df["close"].shift(-1)
    df["future_return"] = (df["next_close"] - df["close"]) / df["close"]
    df = df.dropna(subset=["future_return"])
    return df


# =====================================================================
# FIT WEIGHTS BASED ON HISTORICAL CORRELATION
# =====================================================================
def _fit_weights(df):
    new_weights = {}

    factors = {
        "momentum_weight": df["momentum10"],
        "volatility_weight": df["volatility20"] * -1,    # lower vol = better
        "trend_weight": df["slope10"],
        "hybrid_weight": df["hybrid_score"],
        "confidence_weight": df["confidence"]
    }

    for weight_name, series in factors.items():
        corr = df["future_return"].corr(series)
        if pd.isna(corr):
            corr = 0.0
        new_weights[weight_name] = corr

    # Normalize so weights sum to 1
    total = sum(abs(v) for v in new_weights.values()) or 1
    for k in new_weights:
        new_weights[k] = float(new_weights[k] / total)

    return new_weights


# =====================================================================
# MAIN TRAINING FUNCTION
# =====================================================================
def train_learning_engine():
    """
    Loads last 90 days of records, learns correlations between
    Astra’s signals and future performance.
    """

    df = load_records(as_dataframe=True)
    if df.empty or len(df) < 50:
        return LEARNING_STATE  # Not enough data yet

    # Guardian cleanup
    df = guardian.sanitize_df(df)

    # Compute training targets (next-day returns)
    df = _compute_targets(df)
    if df.empty:
        return LEARNING_STATE

    # Drop rows with missing numeric data
    numeric_cols = [
        "momentum10", "volatility20", "slope10",
        "hybrid_score", "confidence",
        "future_return"
    ]
    df = df.dropna(subset=numeric_cols)

    if df.empty:
        return LEARNING_STATE

    # Fit new weights
    new_weights = _fit_weights(df)

    # Update global state
    LEARNING_STATE.update(new_weights)
    LEARNING_STATE["last_trained"] = datetime.utcnow().isoformat()
    LEARNING_STATE["samples_used"] = len(df)

    return LEARNING_STATE


# =====================================================================
# PREDICTIVE SIGNAL — Combined Learning Score
# Used by Ranking Engine.
# =====================================================================
def learning_signal(feature_row):
    """
    feature_row is a dict containing:
       momentum10, volatility20, slope10, hybrid_score, confidence
    """

    w = LEARNING_STATE

    # Guardian-safe extraction
    m = feature_row.get("momentum10", 0)
    v = feature_row.get("volatility20", 0)
    t = feature_row.get("slope10", 0)
    h = feature_row.get("hybrid_score", 0)
    c = feature_row.get("confidence", 0)

    # Lower volatility → better
    v_score = -v

    # Weighted composite score
    final = (
        w["momentum_weight"]   * m +
        w["volatility_weight"] * v_score +
        w["trend_weight"]      * t +
        w["hybrid_weight"]     * h +
        w["confidence_weight"] * c
    )

    return float(final)


# =====================================================================
# EXTERNAL API FOR RANKING ENGINE
# =====================================================================
def get_learning_state():
    return LEARNING_STATE


def refresh_learning():
    """Train immediately and return updated weights."""
    return train_learning_engine()
