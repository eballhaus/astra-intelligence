"""
feature_builder.py — Phase-90
Builds the full feature vector for every ticker.

This module extracts:
 • Momentum Features
 • Volatility Features
 • Technical Indicators
 • Volume Features
 • Psychology / Catalyst placeholders
 • Sparkline and Price-action Features
 • Normalized ML-ready vector (NeuralAgent input)
"""

import numpy as np
import pandas as pd


class FeatureBuilder:
    """Constructs numerical features for ML + agents."""

    def __init__(self):
        pass

    # -------------------------------------------------------
    # SAFE ACCESS HELPERS
    # -------------------------------------------------------
    def safe(self, value, default=0.0):
        """Return value or default if None/NaN/inf."""
        if value is None:
            return default
        if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
            return default
        return float(value)

    # -------------------------------------------------------
    # MOMENTUM FEATURES
    # -------------------------------------------------------
    def momentum_features(self, df: pd.DataFrame):
        """Extract momentum metrics from OHLCV."""

        try:
            close = df["close"]
            returns = close.pct_change()

            # ROC — Rate of Change
            roc_5 = self.safe((close.iloc[-1] - close.iloc[-6]) / close.iloc[-6])
            roc_10 = self.safe((close.iloc[-1] - close.iloc[-11]) / close.iloc[-11])

            # Price slope over 10 periods
            slope = np.polyfit(range(len(close.tail(10))), close.tail(10), 1)[0]
            slope_norm = slope / close.iloc[-1]

        except Exception:
            roc_5 = roc_10 = slope_norm = 0.0

        return {
            "roc_5": roc_5,
            "roc_10": roc_10,
            "slope_norm": slope_norm,
        }

    # -------------------------------------------------------
    # VOLATILITY FEATURES
    # -------------------------------------------------------
    def volatility_features(self, df: pd.DataFrame):
        """Measure price volatility."""
        try:
            returns = df["close"].pct_change()
            vol = self.safe(returns.std())
        except Exception:
            vol = 0.0

        return {"volatility": vol}

    # -------------------------------------------------------
    # TECHNICAL INDICATORS
    # -------------------------------------------------------
    def technical_features(self, df: pd.DataFrame):
        """RSI, MACD, MA ratios, etc."""

        try:
            close = df["close"]

            # --- Moving Averages ---
            ma10 = close.rolling(10).mean().iloc[-1]
            ma30 = close.rolling(30).mean().iloc[-1]
            ma_ratio = self.safe(ma10 / ma30)

            # --- RSI ---
            delta = close.diff()
            gain = np.where(delta > 0, delta, 0)
            loss = np.where(delta < 0, -delta, 0)
            avg_gain = pd.Series(gain).rolling(14).mean().iloc[-1]
            avg_loss = pd.Series(loss).rolling(14).mean().iloc[-1]
            rs = avg_gain / avg_loss if avg_loss != 0 else 0
            rsi = 100 - (100 / (1 + rs))

            # --- MACD ---
            ema12 = close.ewm(span=12).mean().iloc[-1]
            ema26 = close.ewm(span=26).mean().iloc[-1]
            macd = self.safe(ema12 - ema26)

        except Exception:
            ma_ratio = rsi = macd = 0.0

        return {
            "ma_ratio": ma_ratio,
            "rsi": rsi,
            "macd": macd,
        }

    # -------------------------------------------------------
    # VOLUME FEATURES
    # -------------------------------------------------------
    def volume_features(self, df: pd.DataFrame):
        """Volume spikes."""
        try:
            vol = df["volume"]
            vol_norm = self.safe(vol.iloc[-1] / vol.rolling(20).mean().iloc[-1])
        except Exception:
            vol_norm = 1.0

        return {"vol_spike": vol_norm}

    # -------------------------------------------------------
    # SPARKLINE FEATURES
    # -------------------------------------------------------
    def sparkline_features(self, df: pd.DataFrame):
        """Measures short-term price curvature."""
        try:
            close = df["close"].tail(20)
            x = np.arange(len(close))
            coeffs = np.polyfit(x, close, 2)  # quadratic curvature
            curvature = self.safe(coeffs[0])
        except Exception:
            curvature = 0.0

        return {"curvature": curvature}

    # -------------------------------------------------------
    # PSYCHOLOGY & CATALYST PLACEHOLDERS
    # -------------------------------------------------------
    def psychology_features(self, psychology_data=None):
        """Placeholder for Fear/Greed, VIX, etc."""
        if not psychology_data:
            return {"psych_score": 0.0}

        return {"psych_score": self.safe(psychology_data.get("score", 0.0))}

    def catalyst_features(self, catalyst_data=None):
        """Placeholder for news bursts, earnings, macro."""
        if not catalyst_data:
            return {"catalyst_score": 0.0}

        return {"catalyst_score": self.safe(catalyst_data.get("score", 0.0))}

    # -------------------------------------------------------
    # MAIN FEATURE VECTOR BUILDER
    # -------------------------------------------------------
    def build_features(self, df: pd.DataFrame,
                       psychology_data=None,
                       catalyst_data=None):
        """
        Returns:
           full_feature_dict (for agents)
           neural_vector (for NeuralAgent)
        """

        if df is None or len(df) < 40:
            # fallback empty feature set
            return {}, np.zeros(12)

        # --- Extract all feature groups ---
        f_mom = self.momentum_features(df)
        f_vol = self.volatility_features(df)
        f_tech = self.technical_features(df)
        f_volu = self.volume_features(df)
        f_spark = self.sparkline_features(df)
        f_psy = self.psychology_features(psychology_data)
        f_cat = self.catalyst_features(catalyst_data)

        # Merge full dictionary
        full = {
            **f_mom,
            **f_vol,
            **f_tech,
            **f_volu,
            **f_spark,
            **f_psy,
            **f_cat,
        }

        # --- Neural Model Vector ---
        neural_vector = np.array([
            self.safe(full["roc_5"]),
            self.safe(full["roc_10"]),
            self.safe(full["slope_norm"]),
            self.safe(full["volatility"]),
            self.safe(full["ma_ratio"]),
            self.safe(full["rsi"]) / 100.0,
            self.safe(full["macd"]),
            self.safe(full["vol_spike"]),
            self.safe(full["curvature"]),
            self.safe(full["psych_score"]),
            self.safe(full["catalyst_score"]),
        ])

        return full, neural_vector
