"""
ranking_engine.py — Phase-90

Ranks tickers based on:
 • Astra Score (primary)
 • Momentum Strength
 • Technical Alignment
 • Volatility Quality
 • Neural Probability
Produces a single sortable numeric rank_score.
"""

class RankingEngine:
    def __init__(self):
        pass

    def safe(self, v, default=0.0):
        try:
            if v is None:
                return default
            if isinstance(v, float) and (v != v):  # NaN
                return default
            return float(v)
        except Exception:
            return default

    def extract_scores(self, packet: dict):
        """Extract important scoring elements from AstraPrime packet."""
        if not isinstance(packet, dict):
            return {
                "astra_score": 0.0,
                "momentum": 0.5,
                "technical": 0.5,
                "risk": 0.5,
                "neural": 0.5,
            }

        agents = packet.get("agent_scores", {})

        return {
            "astra_score": self.safe(packet.get("astra_score", 0.0)),
            "momentum": self.safe(agents.get("momentum", 0.5)),
            "technical": self.safe(agents.get("technical", 0.5)),
            "risk": self.safe(agents.get("risk", 0.5)),
            "neural": self.safe(agents.get("neural", 0.5)),
        }

    def compute_rank_score(self, s):
        """
        Combine all model signals into one master rank score.

        Weighted:
         • Astra Score      50%
         • Momentum         20%
         • Technical        20%
         • Neural Prob      10%
        """
        try:
            return float(
                0.50 * s["astra_score"] +
                0.20 * s["momentum"] +
                0.20 * s["technical"] +
                0.10 * s["neural"]
            )
        except Exception:
            return 0.0

    def rank(self, packets: dict):
        """
        packets = {
            "AAPL": <AstraPrime packet>,
            "MSFT": <packet>,
            ...
        }

        Returns list sorted by highest rank score:
        [
            { "ticker": "AAPL", "rank_score": 0.89, ... },
            ...
        ]
        """
        ranked = []

        if not isinstance(packets, dict):
            return ranked

        for ticker, packet in packets.items():
            s = self.extract_scores(packet)
            rank_score = self.compute_rank_score(s)

            ranked.append({
                "ticker": ticker,
                "rank_score": rank_score,
                "packet": packet,
            })

        # highest first
        ranked.sort(key=lambda x: x["rank_score"], reverse=True)
        return ranked
