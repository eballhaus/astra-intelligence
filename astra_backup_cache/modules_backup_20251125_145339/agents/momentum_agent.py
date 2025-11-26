"""
MomentumAgent — Phase-90

Evaluates short- and mid-term price momentum using:
 • 5-day ROC
 • 10-day ROC
 • Momentum slope
Outputs a normalized 0–1 score.
"""

class MomentumAgent:
    def __init__(self):
        pass

    def safe(self, value, default=0.0):
        """Return a safe float."""
        try:
            if value is None:
                return default
            if isinstance(value, float) and (value != value):  # NaN check
                return default
            return float(value)
        except Exception:
            return default

    def normalize(self, x, low=-0.10, high=0.10):
        """
        Normalize ROC-like values to 0–1 scale.
        Clamps outside the range.
        """
        try:
            if x <= low:
                return 0.0
            if x >= high:
                return 1.0
            return (x - low) / (high - low)
        except Exception:
            return 0.5

    def run(self, inputs: dict) -> float:
        """
        inputs = {
            "roc_5": ...,
            "roc_10": ...,
            "slope_norm": ...
        }
        """

        if not isinstance(inputs, dict):
            return 0.5

        roc_5 = self.safe(inputs.get("roc_5", 0.0))
        roc_10 = self.safe(inputs.get("roc_10", 0.0))
        slope = self.safe(inputs.get("slope_norm", 0.0))

        # Normalize
        roc5_score = self.normalize(roc_5)
        roc10_score = self.normalize(roc_10)
        slope_score = self.normalize(slope)

        # Weighted momentum score
        score = (
            0.4 * roc5_score +
            0.4 * roc10_score +
            0.2 * slope_score
        )

        return float(score)
