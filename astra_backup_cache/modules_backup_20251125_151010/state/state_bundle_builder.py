"""
state_bundle_builder.py — Phase-90

Consolidates all inputs for AstraPrime:
 • Technical indicators
 • Momentum values
 • Volume / Volatility
 • Sparkline
 • Psychology + Catalyst signals
 • Neural input vector (12-dimensional)
"""

import numpy as np


class StateBundleBuilder:
    def __init__(self):
        pass

    # -------------------------------------------------------------
    # SAFE HELPERS
    # -------------------------------------------------------------
    def safe(self, val, default=None):
        try:
            if val is None:
                return default
            if isinstance(val, float) and (val != val):  # NaN
                return default
            return val
        except Exception:
            return default

    def to_float(self, v, default=0.0):
        try:
            return float(v)
        except Exception:
            return default

    # -------------------------------------------------------------
    # CORE BUNDLE
    # -------------------------------------------------------------
    def build_bundle(
        self,
        ticker,
        df,
        fetch_meta=None,
        psychology_data=None,
        catalyst_data=None,
    ):
        """
        df: DataFrame from fetch_unified (contains technicals)
        fetch_meta: last price, sparkline, etc.
        psychology_data: fear/greed placeholder or API feed
        catalyst_data: earnings/news placeholder or API feed
        """

        # --------------------------
        # EXTRACT TECHNICAL SIGNALS
        # --------------------------
        rsi = self.to_float(df["rsi"].iloc[-1], 50)
        macd = self.to_float(df["macd"].iloc[-1], 0)
        ma_ratio = self.to_float(df["ma10"].iloc[-1] / df["ma30"].iloc[-1], 1.0)

        # --------------------------
        # MOMENTUM + VOLATILITY
        # --------------------------
        momentum = self.to_float(df["momentum"].iloc[-1], 0.0)
        volatility = self.to_float(df["volatility"].iloc[-1], 0.02)

        # --------------------------
        # VOLUME
        # --------------------------
        vol_spike = self.to_float(df["vol_spike"].iloc[-1], 1.0)

        # --------------------------
        # EXTERNAL SIGNALS
        # --------------------------
        psych_score = self.safe(psychology_data, 0.5)
        catalyst_score = self.safe(catalyst_data, 0.0)

        # --------------------------
        # SPARKLINE + PRICE
        # --------------------------
        spark = []
        last_price = 0.0
        if fetch_meta:
            spark = self.safe(fetch_meta.get("sparkline", []), [])
            last_price = self.safe(fetch_meta.get("last_price", 0), 0.0)

        # --------------------------
        # NEURAL FEATURE VECTOR
        # --------------------------
        vector = np.array([
            rsi / 100.0,
            macd,
            ma_ratio,
            momentum,
            volatility,
            vol_spike,
            psych_score,
            catalyst_score,
            last_price / 1000.0,
            (df["close"].pct_change().iloc[-5:].mean()),
            (df["close"].pct_change().iloc[-20:].mean()),
            (df["close"].pct_change().iloc[-1]),
        ], dtype=float)

        # --------------------------
        # OUTPUT STRUCTURE
        # --------------------------
        return {
            "ticker": ticker,
            "technical": {
                "rsi": rsi,
                "macd": macd,
                "ma_ratio": ma_ratio,
            },
            "momentum": momentum,
            "volatility": volatility,
            "vol_spike": vol_spike,
            "psychology": psych_score,
            "catalyst": catalyst_score,
            "fetch_meta": {
                "sparkline": spark,
                "last_price": last_price,
            },
            "neural_vector": vector,
        }
