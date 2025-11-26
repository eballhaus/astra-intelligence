"""
PsychologyAgent — Phase-90

Processes sentiment / Fear-Greed / psychological indicators.
"""

class PsychologyAgent:
    def __init__(self):
        pass

    def safe(self, value, default=0.5):
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
            "psych_score": ...
        }
        """
        if not isinstance(inputs, dict):
            return 0.5

        score = self.safe(inputs.get("psych_score", 0.5))
        # Already roughly 0–1 scaled
        return max(0.0, min(1.0, score))
