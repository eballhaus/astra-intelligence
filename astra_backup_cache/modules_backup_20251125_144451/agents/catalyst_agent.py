"""
CatalystAgent — Phase-90

Evaluates catalyst conditions such as:
 • Earnings
 • News sentiment
 • Macro catalysts
Outputs a normalized 0–1 signal.
"""

class CatalystAgent:
    def __init__(self):
        pass

    def safe(self, value, default=0.0):
        try:
            if value is None:
                return default
            if isinstance(value, float) and (value != value):
                return default
            return float(value)
        except Exception:
            return default

    def run(self, inputs: dict) -> float:
        """
        inputs = {
            "catalyst_score": ...
        }
        """
        if not isinstance(inputs, dict):
            return 0.5

        score = self.safe(inputs.get("catalyst_score", 0.0))
        return max(0.0, min(1.0, score))
