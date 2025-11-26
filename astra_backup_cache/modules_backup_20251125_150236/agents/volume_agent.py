"""
VolumeAgent — Phase-90

Evaluates volume behavior using:
 • Relative Volume (RVOL)
 • Spike over 20-day average
Outputs a normalized 0–1 score.
"""

class VolumeAgent:
    def __init__(self):
        pass

    def safe(self, value, default=1.0):
        try:
            if value is None:
                return default
            if isinstance(value, float) and (value != value):  # NaN
                return default
            return float(value)
        except Exception:
            return default

    def normalize(self, vol_spike):
        """
        Normalize vol_spike (RVOL) to 0–1.
        1.0 = normal volume
        >1.0 = high volume
        <1.0 = low volume
        """
        try:
            if vol_spike <= 0.5:
                return 0.0
            if vol_spike >= 2.0:
                return 1.0
            return (vol_spike - 0.5) / (2.0 - 0.5)
        except Exception:
            return 0.5

    def run(self, inputs: dict) -> float:
        """
        inputs = {
            "vol_spike": ...
        }
        """

        if not isinstance(inputs, dict):
            return 0.5

        vol = self.safe(inputs.get("vol_spike", 1.0))

        score = self.normalize(vol)
        return float(score)
