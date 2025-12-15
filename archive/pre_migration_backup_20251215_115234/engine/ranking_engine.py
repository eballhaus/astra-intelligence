"""
Astra Intelligence — RankingEngine (v2 Safe Integration)
--------------------------------------------------------
Ranks symbols based on Astra's AI signals and assigns buy grades.
"""

import numpy as np

import pandas as pd


class RankingEngine:
    """
    Generates buy/sell grades based on performance, volatility, and momentum.
    """

    def __init__(self):
        self.grade_thresholds = {
            "A+": 90,
            "A": 80,
            "B+": 70,
            "B": 60,
            "C": 50,
            "D": 40,
            "F": 0,
        }

    def get_score(self, df: pd.DataFrame):
        """
        Calculate a numeric score (0–100) based on recent performance metrics.
        """
        try:
            if df is None or df.empty or "close" not in df.columns:
                return 0

            closes = df["close"].astype(float)
            returns = closes.pct_change().dropna()
            momentum = (closes.iloc[-1] / closes.iloc[-5]) - 1 if len(closes) > 5 else 0
            volatility = returns.std() * 100

            # Simple scoring formula
            score = (momentum * 100) - (volatility * 0.5)
            score = np.clip(score, 0, 100)

            return round(score, 2)
        except Exception as e:
            print(f"[RankingEngine] get_score() error: {e}")
            return 0

    def get_grade(self, symbol: str, df: pd.DataFrame):
        """
        Return a letter grade (A–F) and numeric score for the asset.
        """
        score = self.get_score(df)
        grade = "F"
        for label, threshold in self.grade_thresholds.items():
            if score >= threshold:
                grade = label
                break
        return grade

# ============================================================
# Phase 7 Learning Integration Patch (Astra v4.5 → v7)
# ============================================================
try:
    from learning.neural_agent import NeuralAgent
    from learning.replay_buffer import ReplayBuffer
    import threading
    import time

    _astra_learning_ready = True
    _neural_agent = NeuralAgent()
    _replay_buffer = ReplayBuffer()

    def start_learning_loop():
        """Background learning thread (non-blocking)."""
        def _loop():
            while True:
                try:
                    batch = _replay_buffer.sample()
                    if batch:
                        _neural_agent.learn(batch)
                except Exception as e:
                    print(f"[Astra Learning Loop] Warning: {e}")
                time.sleep(5)
        t = threading.Thread(target=_loop, daemon=True)
        t.start()

    # Launch learning loop asynchronously after FastBoot init
    start_learning_loop()

except Exception as e:
    _astra_learning_ready = False
    print(f"[Astra Phase7 Integration] Learning not initialized: {e}")
# ============================================================
