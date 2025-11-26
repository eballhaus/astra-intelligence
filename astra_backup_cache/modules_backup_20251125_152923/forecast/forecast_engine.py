"""
Astra 7.0 - Forecast Engine
---------------------------
Simple placeholder forecasting module used by Astra.

Provides:
    • get_forecast(symbol) → dict
    • run_forecast(symbol)  (alias)
"""

from datetime import datetime


def get_forecast(symbol: str):
    """
    Returns a minimal forecast dictionary so the UI can render safely.
    Future versions will provide real ML forecasting.
    """
    return {
        "symbol": symbol.upper(),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "trend": "neutral",
        "confidence": 0.50,
        "prediction": "No strong signal",
        "model": "Astra Forecast v1 (placeholder)"
    }


def run_forecast(symbol: str):
    """
    Backward-compatible alias for older calls.
    """
    return get_forecast(symbol)
