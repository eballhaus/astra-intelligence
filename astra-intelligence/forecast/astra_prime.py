from core.astra_prime import AstraPrime


def get_predictions(symbol: str) -> dict:
    """
    Public interface for the UI. Returns Astra Prime’s live forecast
    for a single ticker.
    """
    try:
        prime = AstraPrime()  # main class from your Astra engine
        result = prime.predict(symbol)  # existing method in your engine
        return {
            "price": round(float(result.get("target_price", 0)), 2),
            "percent": round(float(result.get("expected_return", 0)), 2),
            "timeframe": result.get("timeframe", "7 d"),
            "stop_loss": round(float(result.get("stop_loss", 0)), 2),
            "confidence": round(float(result.get("confidence", 0)), 1),
            "grade": result.get("grade", "B"),
            "reason": result.get(
                "reason",
                "Astra algorithms identified favorable technical and sentiment alignment.",
            ),
        }
    except Exception as e:
        return {
            "price": 0,
            "percent": 0,
            "timeframe": "N/A",
            "stop_loss": 0,
            "confidence": 0,
            "grade": "N/A",
            "reason": f"⚠️ AstraPrime prediction unavailable: {e}",
        }
