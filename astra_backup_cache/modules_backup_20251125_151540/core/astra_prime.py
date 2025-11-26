"""
astra_prime.py — Phase-90

Main multi-agent scoring engine for Astra Intelligence.

Enhancements:
 • agent weighting system
 • dynamic weight optimizer (Phase-100 hook)
 • clean integration with StateBundleBuilder & NeuralAgent
"""

import numpy as np

from astra_modules.agents.momentum_agent import MomentumAgent
from astra_modules.agents.volume_agent import VolumeAgent
from astra_modules.agents.risk_agent import RiskAgent
from astra_modules.agents.psychology_agent import PsychologyAgent
from astra_modules.agents.catalyst_agent import CatalystAgent
from astra_modules.agents.technical_agent import TechnicalAgent
from astra_modules.agents.neural_agent import NeuralAgent


class AstraPrime:
    def __init__(self):
        # Agents
        self.momentum = MomentumAgent()
        self.volume = VolumeAgent()
        self.risk = RiskAgent()
        self.psych = PsychologyAgent()
        self.catalyst = CatalystAgent()
        self.technical = TechnicalAgent()
        self.neural = NeuralAgent()

        # Agent weights (will be optimized in Phase-100)
        self.weights = {
            "momentum": 0.15,
            "volume": 0.10,
            "risk": 0.10,
            "psych": 0.10,
            "catalyst": 0.10,
            "technical": 0.20,
            "neural": 0.25,
        }

    # -----------------------------------------------------------
    # SAFE VALUE
    # -----------------------------------------------------------
    def safe(self, v, default=0.0):
        try:
            if v is None:
                return default
            if isinstance(v, float) and (v != v):
                return default
            return float(v)
        except Exception:
            return default

    # -----------------------------------------------------------
    # MAIN RUN FUNCTION
    # -----------------------------------------------------------
    def run(self, ticker, df, fetch_meta, psychology_data, catalyst_data):
        """
        Called by ScanManager.

        Returns rich packet:
         • agent scores
         • final Astra score
         • buy grade
         • metadata
        """

        # Build agent inputs from df and meta
        latest = {
            "rsi": self.safe(df["rsi"].iloc[-1], 50),
            "macd": self.safe(df["macd"].iloc[-1], 0),
            "ma_ratio": self.safe(df["ma10"].iloc[-1] / df["ma30"].iloc[-1], 1),
            "momentum": self.safe(df["momentum"].iloc[-1], 0),
            "volatility": self.safe(df["volatility"].iloc[-1], 0.02),
            "vol_spike": self.safe(df["vol_spike"].iloc[-1], 1),
            "psych_score": self.safe(psychology_data, 0.5),
            "catalyst_score": self.safe(catalyst_data, 0.0),
        }

        # Agent outputs
        a = {
            "momentum": self.momentum.run({"momentum": latest["momentum"]}),
            "volume": self.volume.run({"vol_spike": latest["vol_spike"]}),
            "risk": self.risk.run({"volatility": latest["volatility"]}),
            "psych": self.psych.run({"psych_score": latest["psych_score"]}),
            "catalyst": self.catalyst.run({"catalyst_score": latest["catalyst_score"]}),
            "technical": self.technical.run({
                "rsi": latest["rsi"],
                "macd": latest["macd"],
                "ma_ratio": latest["ma_ratio"],
            }),
        }

        # Neural input vector
        vector = np.array([
            latest["rsi"] / 100,
            latest["macd"],
            latest["ma_ratio"],
            latest["momentum"],
            latest["volatility"],
            latest["vol_spike"],
            latest["psych_score"],
            latest["catalyst_score"],
            fetch_meta.get("last_price", 0) / 1000.0,
            (df["close"].pct_change().iloc[-5:].mean()),
            (df["close"].pct_change().iloc[-20:].mean()),
            (df["close"].pct_change().iloc[-1]),
        ], dtype=float)

        a["neural"] = self.neural.predict(vector)

        # Weighted Astra score
        score = 0
        for agent, s in a.items():
            score += s * self.weights[agent]

        # Convert to grade A+ / A / B / etc.
        grade = self.grade(score)

        # Output packet
        return {
            "ticker": ticker,
            "astra_score": float(score),
            "grade": grade,
            "agent_scores": a,
            "fetch_meta": fetch_meta,
        }

    # -----------------------------------------------------------
    # GRADING SYSTEM
    # -----------------------------------------------------------
    def grade(self, score):
        if score >= 0.80: return "A+"
        if score >= 0.70: return "A"
        if score >= 0.60: return "B"
        if score >= 0.50: return "C"
        if score >= 0.40: return "D"
        return "F"
