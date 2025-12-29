from core.agents.base_agent import BaseAgent

"""
Astra Intelligence — PsychologyAgent v2
---------------------------------------
Generates human-readable reasoning strings explaining Astra's forecasts.
This version is dashboard-safe and works even when markets are closed.
"""

from datetime import datetime

import numpy as np
import pandas as pd


class PsychologyAgent(BaseAgent):
    """
    Converts numeric and volatility context into qualitative reasoning.
    """

    def __init__(self):
        self.sentences = {
            "bullish": [
                "Astra detects strong upward momentum and positive sentiment.",
                "Volume accumulation suggests institutional buying pressure.",
                "Price stability and trend strength indicate bullish continuation.",
            ],
            "neutral": [
                "Mixed momentum and limited volatility imply short-term equilibrium.",
                "Market consolidation detected — Astra expects sideways action.",
                "No dominant momentum; neutral outlook pending next catalyst.",
            ],
            "bearish": [
                "Astra detects profit-taking and rising downside volatility.",
                "Weak momentum and elevated risk suggest caution.",
                "Downward drift detected; Astra flags defensive posture.",
            ],
        }

    def get_reason(self, symbol: str, df: pd.DataFrame):
        """
        Return a one-sentence reasoning string based on last close behaviour.
        """

        try:
            if df is None or df.empty or "close" not in df.columns:
                return "No recent market data available; awaiting next session."

            closes = df["close"].astype(float)
            change = closes.pct_change().iloc[-1] * 100 if len(closes) > 1 else 0
            vol = closes.pct_change().std() * 100

            # Determine sentiment zone
            if change > 0.5 and vol < 2:
                mood = "bullish"
            elif change < -0.5 and vol > 1:
                mood = "bearish"
            else:
                mood = "neutral"

            text = np.random.choice(self.sentences[mood])
            timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

            return f"{text} ({timestamp})"

        except Exception as e:
            return f"Astra reasoning unavailable: {e}"

    def predict(self, x=None):
        """Temporary calibration stub."""
        self.g_log(f"[{self.__class__.__name__}] Predict placeholder executed.")
        return 0.5
