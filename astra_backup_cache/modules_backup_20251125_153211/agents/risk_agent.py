"""
RiskAgent — Phase-90

Scores volatility (risk).
Lower volatility = higher score.
Higher volatility = lower score.
"""

class RiskAgent:
    def __init__(self):
        pass

    def safe(self, value, default=0.02):
        try:
            if value is None:
                return default
            if isinstance(value, float) and (value != value):  # NaN
                return default
            return float(value)
        except Exception:
            return default

    def normalize(self, vol):
        """
        Typical daily volatility:
         - stable: <2%
         - moderate: 2–4%
         - high risk: >4%
        Normalize to 0–1 score.
        """
        try:
            if vol >= 0.06:
                return 0.0
            if vol <= 0.01:
                return 1.0
            return 1.0 - ((vol - 0.01) / (0.06 - 0.01))
        except Exception:
            return 0.5

    def run(self, inputs: dict) -> float:
        """
        inputs = {
            "volatility": ...
        }
        """

        if not isinstance(inputs, dict):
            return 0.5

        vol = self.safe(inputs.get("volatility", 0.02))

        score = self.normalize(vol)
        return float(score)
