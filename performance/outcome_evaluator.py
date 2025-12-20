# Astra Performance System — outcome_evaluator.py
"""
Astra Intelligence — Outcome Evaluator
--------------------------------------
Calculates profit/loss and correctness for closed trades.
"""

import time


class OutcomeEvaluator:
    def compute_return(self, entry_price, exit_price, direction):
        if direction == "BUY":
            return (exit_price - entry_price) / entry_price
        elif direction == "SELL":
            return (entry_price - exit_price) / entry_price
        return 0.0

    def compute_correctness(self, entry_price, exit_price, direction):
        r = self.compute_return(entry_price, exit_price, direction)
        return 1 if r > 0 else 0

    def evaluate(self, prediction, exit_price):
        entry = prediction["price"]
        direction = prediction["direction"]
        return {
            "exit_price": exit_price,
            "return_pct": self.compute_return(entry, exit_price, direction),
            "correct": self.compute_correctness(entry, exit_price, direction),
            "closed_timestamp": time.time(),
        }
