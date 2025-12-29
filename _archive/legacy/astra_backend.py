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
