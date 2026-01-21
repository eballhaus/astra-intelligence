# -*- coding: utf-8 -*-
"""
Astra Intelligence — Minimal FastAPI Backend (v1)
Provides /v1/data/{symbol} endpoint for dashboard_data and orchestrator testing.
"""

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from datetime import datetime, timezone
import random

app = FastAPI(title="Astra Intelligence Backend")


@app.get("/v1/data/{symbol}")
def get_data(symbol: str):
    """Synthetic endpoint: generates random OHLC data for testing."""
    now = datetime.now(timezone.utc)
    data = []
    for i in range(60):
        base = 100 + random.uniform(-5, 5)
        data.append(
            {
                "timestamp": (now).isoformat(),
                "open": base - 1,
                "high": base + 1,
                "low": base - 2,
                "close": base,
                "volume": random.randint(1000, 5000),
            }
        )
    return JSONResponse(content={"data": data})


# === Astra Dashboard Integration Routes ===

@app.get("/health")
def health_check():
    """System status for Astra Dashboard."""
    return {
        "status": "ok",
        "guardian": "v7",
        "funnel": "v11",
        "sentinel": "Tier 2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/signals")
def get_signals():
    """Return Astra's top-performing stock and crypto signals."""
    sample = {
        "stocks": [
            {"symbol": "NVDA", "type": "stock", "grade": "A+", "confidence": 97.4, "signal": "Strong Buy", "price": 514.78, "change": 0.32},
            {"symbol": "AAPL", "type": "stock", "grade": "A", "confidence": 94.2, "signal": "Buy", "price": 199.24, "change": 0.18},
            {"symbol": "TSLA", "type": "stock", "grade": "A", "confidence": 91.6, "signal": "Momentum", "price": 271.38, "change": 0.51},
            {"symbol": "MSFT", "type": "stock", "grade": "B+", "confidence": 89.7, "signal": "Buy", "price": 370.14, "change": -0.09},
            {"symbol": "AMZN", "type": "stock", "grade": "B+", "confidence": 87.3, "signal": "Hold", "price": 149.23, "change": -0.13},
            {"symbol": "GOOGL", "type": "stock", "grade": "A", "confidence": 92.8, "signal": "Strong Buy", "price": 140.56, "change": 0.45},
        ],
        "cryptos": [
            {"symbol": "BTC", "type": "crypto", "grade": "A+", "confidence": 95.1, "signal": "Long Momentum", "price": 51325.41, "change": 0.72},
            {"symbol": "ETH", "type": "crypto", "grade": "A", "confidence": 93.3, "signal": "Buy", "price": 2471.65, "change": 0.39},
            {"symbol": "SOL", "type": "crypto", "grade": "B+", "confidence": 89.1, "signal": "Strong Buy", "price": 78.31, "change": 1.23},
            {"symbol": "ADA", "type": "crypto", "grade": "B", "confidence": 86.4, "signal": "Buy", "price": 0.62, "change": 0.17},
            {"symbol": "XRP", "type": "crypto", "grade": "B", "confidence": 83.9, "signal": "Hold", "price": 0.54, "change": -0.08},
            {"symbol": "AVAX", "type": "crypto", "grade": "A-", "confidence": 91.2, "signal": "Strong Buy", "price": 42.18, "change": 1.11},
        ],
    }
    return sample


@app.get("/chart")
def get_chart():
    """Return synthetic chart data for NVDA."""
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(50):
        base = 100 + random.uniform(-5, 5)
        candles.append(
            {
                "time": (now).isoformat(),
                "open": base - 1,
                "high": base + 1,
                "low": base - 2,
                "close": base,
                "volume": random.randint(1000, 5000),
            }
        )
    return candles

@app.get("/health")
def get_health():
    """Basic system health check."""
    return {"status": "ok", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/signals")
def get_signals():
    """Return synthetic signals for testing."""
    sample_signals = {
        "BTC": random.choice(["BUY", "SELL", "HOLD"]),
        "NVDA": random.choice(["BUY", "SELL", "HOLD"]),
        "TSLA": random.choice(["BUY", "SELL", "HOLD"]),
    }
    return sample_signals


@app.get("/chart")
def get_chart():
    """Return synthetic chart data for NVDA."""
    now = datetime.now(timezone.utc)
    candles = []
    for i in range(50):
        base = 100 + random.uniform(-5, 5)
        candles.append(
            {
                "time": (now).isoformat(),
                "open": base - 1,
                "high": base + 1,
                "low": base - 2,
                "close": base,
                "volume": random.randint(1000, 5000),
            }
        )
    return candles

@app.get("/ping")
def ping():
    return {"msg": "pong"}
