# -*- coding: utf-8 -*-
"""
Astra Intelligence - Funnel System
Responsible for generating ranked stock and crypto predictions.
"""

import random
import datetime

class AstraFunnel:
    def __init__(self):
        """Initialize Astra Funnel."""
        self.timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def run(self, mode="stocks", context=None):
        """
        Run the Astra Funnel intelligence pipeline.
        Returns top 6 ranked predictions.
        """
        try:
            # Define candidate pools
            if mode == "crypto":
                pool = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "BNB-USD", "AVAX-USD"]
            else:
                pool = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "META", "NFLX", "AMD", "GOOGL", "SHOP"]

            # Rank and score
            ranked = self._rank_assets(pool)

            # Package results
            results = []
            for symbol, score in ranked[:6]:
                grade = self._get_grade(score)
                results.append({
                    "symbol": symbol,
                    "grade": grade,
                    "confidence": score,
                    "summary": f"{symbol} shows {grade}-level momentum ({score:.1f}% confidence)",
                    "timestamp": self.timestamp
                })
            return results

        except Exception as e:
            print(f"[AstraFunnel] Error: {e}")
            return []

    def _rank_assets(self, pool):
        """
        Mock ranking logic.
        Replace this with multi-agent scoring (MomentumAgent, RiskAgent, etc.)
        """
        random.seed(datetime.datetime.now().timestamp())
        scored = [(symbol, random.uniform(75, 99)) for symbol in pool]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def _get_grade(self, confidence):
        """Convert numeric confidence into letter grade."""
        if confidence >= 95:
            return "A+"
        elif confidence >= 90:
            return "A"
        elif confidence >= 85:
            return "B+"
        elif confidence >= 80:
            return "B"
        else:
            return "C"
