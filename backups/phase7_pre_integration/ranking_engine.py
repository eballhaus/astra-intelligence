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
