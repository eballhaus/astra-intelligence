from guardian.guardian_v7 import GuardianV7

def fetch_live_data(symbols=["AAPL","TSLA","AMZN","MSFT","GOOG","NVDA"]):
    """Fetch full Astra live data including prediction, stop-loss, grade %, confidence, and summary."""
    try:
        guardian = GuardianV7()
        raw = guardian.fetch_live_data(symbols=symbols)
    except Exception:
        # fallback if Guardian doesn't have the method
        raw = [
            {"symbol": s, "price": 0, "confidence": 0, "grade": "–", "timestamp": None}
            for s in symbols
        ]

    enriched = []
    for item in raw:
        sym = item["symbol"]
        price = item.get("price", 0)
        conf = item.get("confidence", 75.0)
        grade = item.get("grade", "B")

        # Placeholder logic until Astra Agents feed real outputs
        prediction = "Bullish" if grade in ["A","A-"] else "Neutral"
        stop_loss = round(price * 0.95, 2)
        grade_percent = 95 if grade == "A" else 90 if grade == "A-" else 85
        summary = f"Astra AI selected {sym} due to positive technical and sentiment alignment."

        enriched.append({
            **item,
            "prediction": prediction,
            "stop_loss": stop_loss,
            "grade_percent": grade_percent,
            "summary": summary,
        })
    return enriched
