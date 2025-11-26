"""
TechnicalAgent — Phase-90

Evaluates trend and market alignment using:
 • RSI
 • MACD
 • MA ratio
"""

class TechnicalAgent:
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

    def normalize_rsi(self, rsi):
        """RSI 30–70 zone → normalized."""
        if rsi <= 20:
            return 0.0
        if rsi >= 80:
            return 1.0
        return (rsi - 20) / 60

    def normalize_macd(self, macd):
        """
        MACD: positive values = bullish,
        negative = bearish.
        """
        if macd <= -1:
            return 0.0
        if macd >= 1:
            return 1.0
        return (macd + 1) / 2

    def normalize_ma(self, ratio):
        """MA ratio above 1 = bullish trend."""
        if ratio <= 0.8:
            return 0.0
        if ratio >= 1.2:
            return 1.0
        return (ratio - 0.8) / 0.4

    def run(self, inputs: dict) -> float:
        """
        inputs = {
            "rsi": ...,
            "macd": ...,
            "ma_ratio": ...
        }
        """

        if not isinstance(inputs, dict):
            return 0.5

        rsi = self.safe(inputs.get("rsi", 50))
        macd = self.safe(inputs.get("macd", 0))
        ma_ratio = self.safe(inputs.get("ma_ratio", 1.0))

        rsi_s = self.normalize_rsi(rsi)
        macd_s = self.normalize_macd(macd)
        ma_s = self.normalize_ma(ma_ratio)

        score = (
            0.4 * rsi_s +
            0.3 * macd_s +
            0.3 * ma_s
        )
        return float(score)
