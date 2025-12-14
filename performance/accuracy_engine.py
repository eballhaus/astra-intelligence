# Astra Performance System — accuracy_engine.py
"""
Astra Intelligence — Accuracy Engine
------------------------------------
Aggregates metrics such as win rate, average return, profit factor, and Sharpe-like score.
"""

import numpy as np


class AccuracyEngine:
    def summarize(self, history):
        if not history:
            return {}

        returns = [p.get("return_pct", 0) for p in history]
        corrects = [p.get("correct", 0) for p in history]

        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r <= 0]

        summary = {
            "total_trades": len(history),
            "win_rate": round(np.mean(corrects), 3),
            "avg_return": round(np.mean(returns), 5),
            "profit_factor": round((sum(wins) / abs(sum(losses) or 1)), 3),
            "sharpe_like": round(
                (np.mean(returns) / (np.std(returns) + 1e-6)) * np.sqrt(len(history)), 3
            ),
        }
        return summary
