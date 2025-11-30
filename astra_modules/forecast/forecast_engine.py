"""
Astra Forecast Engine — Hybrid v2
---------------------------------
Compatible with both:
    - Dashboard imports (ForecastEngine class)
    - Legacy function calls (get_forecast / run_forecast)
"""

from datetime import datetime
import random

# ──────────────────────────────────────────────
# Legacy lightweight forecast functions
# ──────────────────────────────────────────────

def get_forecast(symbol: str):
    """
    Returns a minimal forecast dictionary so the UI can render safely.
    This version provides simple pseudo-predictions and confidence levels.
    """
    direction = random.choice(["bullish", "neutral", "bearish"])
    confidence = round(random.uniform(0.6, 0.9), 2)
    change_pct = random.uniform(-2, 2)

    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trend": direction,
        "confidence": confidence,
        "predicted_change": change_pct,
        "model": "Astra Forecast Hybrid v2",
    }


def run_forecast(symbol: str):
    """Backward-compatible alias for older calls."""
    return get_forecast(symbol)


# ──────────────────────────────────────────────
# Modern dashboard-compatible ForecastEngine class
# ──────────────────────────────────────────────

class ForecastEngine:
    """
    Unified forecasting interface for Astra Intelligence.
    Integrates with the dashboard, learning engine, and future AI models.
    """

    def __init__(self):
        self.model_name = "Astra Forecast Hybrid v2"

    def predict(self, symbol: str, df=None):
        """
        Generates a safe forecast tuple for Astra dashboard integration.
        Returns (predicted_price, predicted_change_pct, confidence)
        """
        try:
            base = get_forecast(symbol)
            change = base["predicted_change"]
            confidence = f"{base['confidence'] * 100:.1f}%"

            # Approximate price projection if DataFrame available
            if df is not None and not df.empty and "close" in df.columns:
                current_price = float(df["close"].iloc[-1])
                predicted_price = current_price * (1 + (change / 100))
            else:
                predicted_price = None

            return predicted_price, change, confidence

        except Exception as e:
            print(f"[ForecastEngine] Forecast error for {symbol}: {e}")
            return None, 0.0, "N/A"
