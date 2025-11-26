"""
state_bundle_builder.py — Phase-90
-----------------------------------
Builds the unified “data_bundle” dictionary consumed by AstraPrime.

Inputs:
    - symbol (str)
    - df (Phase-90 enriched OHLCV DataFrame from fetch_unified)

Outputs:
    {
        "symbol": str,
        "current_price": float,

        # Agent Inputs
        "momentum": {...},
        "volume": {...},
        "risk": {...},
        "psychology": {...},
        "catalyst": {...},
        "technical": {...},
        "neural": [...feature vector...],

        # Shared data
        "sparkline": [...],
        "volatility": float,
        "price_change": float
    }
"""

import numpy as np
import pandas as pd


def build_state_bundle(symbol: str, df: pd.DataFrame):
    if df is None or df.empty:
        return {
            "symbol": symbol,
            "current_price": 0.0,
            "momentum": None,
            "volume": None,
            "risk": None,
            "psychology": None,
            "catalyst": None,
            "technical": None,
            "neural": [0.0] * 8,
            "sparkline": [],
            "volatility": 0.0,
            "price_change": 0.0,
        }

    latest = df.iloc[-1]

    # ---------------------------
    # MOMENTUM INPUT
    # ---------------------------
    momentum_input = df[["date", "close"]].tail(40)

    # ---------------------------
    # VOLUME INPUT
    # ---------------------------
    volume_input = df[["volume"]].tail(40)

    # ---------------------------
    # RISK INPUT
    # ---------------------------
    risk_input = {
        "price_series": df["close"].tail(60).tolist(),
        "volatility": float(latest.get("volatility", 0)),
    }

    # ---------------------------
    # PSYCHOLOGY INPUT
    # Placeholder until full sentiment integration
    # ---------------------------
    psychology_input = {
        "fear_greed": 50,
        "vix": float(latest.get("volatility", 18)),
        "breadth": 50
    }

    # ---------------------------
    # CATALYST INPUT
    # Placeholder until news API added
    # ---------------------------
    catalyst_input = {
        "sentiment_score": 50,
        "event_intensity": 50,
        "news_volume": 1,
        "earnings_flag": False,
        "macro_flag": False,
    }

    # ---------------------------
    # TECHNICAL INPUT
    # ---------------------------
    technical_input = {
        "rsi": float(latest.get("rsi", 50)),
        "macd": float(latest.get("macd", 0)),
        "macd_signal": float(latest.get("macd_signal", 0)),
        "volatility": float(latest.get("volatility", 1)),
        "trend_strength": 60 if latest.get("ma_fast", 0) > latest.get("ma_slow", 0) else 40,
        "ma_fast": float(latest.get("ma_fast", 0)),
        "ma_slow": float(latest.get("ma_slow", 0)),
    }

    # ---------------------------
    # NEURAL FEATURE VECTOR (8-dim)
    # ---------------------------
    neural_features = [
        float(latest.get("rsi", 50)),
        float(latest.get("macd", 0)),
        float(latest.get("macd_signal", 0)),
        float(latest.get("volatility", 0)),
        float(latest.get("price_change", 0)),
        float(technical_input["trend_strength"]),
        float(latest.get("ma_fast", 0)),
        float(latest.get("ma_slow", 0)),
    ]

    # ---------------------------
    # BUILD FINAL BUNDLE
    # ---------------------------
    bundle = {
        "symbol": symbol,
        "current_price": float(latest["close"]),

        "momentum": momentum_input,
        "volume": volume_input,
        "risk": risk_input,
        "psychology": psychology_input,
        "catalyst": catalyst_input,
        "technical": technical_input,
        "neural": neural_features,

        "sparkline": latest.get("sparkline", []),
        "volatility": float(latest.get("volatility", 0)),
        "price_change": float(latest.get("price_change", 0)),
    }

    return bundle
