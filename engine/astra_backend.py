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
    sample_signals = {"BTC": "HOLD", "NVDA": "BUY", "TSLA": "SELL"}
    """Return synthetic signals for testing."""
    sample_signals = {
        "BTC": random.choice(["BUY", "SELL", "HOLD"]),
        "NVDA": random.choice(["BUY", "SELL", "HOLD"]),
        "TSLA": random.choice(["BUY", "SELL", "HOLD"]),
    }
    try:
        enhanced_signals = []
        for sym, sig in sample_signals.items():
            grade = 0.0 if sig == "HOLD" else (0.75 if sig == "BUY" else -0.75)
            components = {"Momentum": grade, "Technical": grade, "Volume": grade}
            enhanced_signals.append(generate_signal_v25(sym, grade, components))
        sample_signals = enhanced_signals
    except Exception as e:
        print(f"[Phase2.5] Enhancement inside get_signals() skipped due to: {e}")
    return sample_signals
@app.get("/ping")
def ping():
    return {"msg": "pong"}

# ============================================================
# ============================================================
from datetime import datetime

def generate_signal_v25(symbol, grade, components):
    """
    Adds confidence tiers, tiered SELL logic, and explainability.
    Purely logic-level; no backend or provider modifications.
    """
    # --- Base signal ---------------------------------------
    if grade >= 0.60:
        signal = "BUY"
    elif grade <= -0.60:
        signal = "SELL"
    else:
        signal = "HOLD"

    # --- Confidence tiers -----------------------------------
    scores = list(components.values())
    spread = max(scores) - min(scores) if scores else 0
    if spread < 0.15:
        confidence = "High"
    elif spread < 0.30:
        confidence = "Medium"
    else:
        confidence = "Low"

    # --- SELL tiering ---------------------------------------
    sell_tier = None
    if signal == "SELL":
        if grade <= -0.6 and grade > -0.8:
            sell_tier = "Profit Protection"
        elif grade <= -0.8 and grade > -0.9:
            sell_tier = "Exit Recommended"
        elif grade <= -0.9:
            sell_tier = "Strong Exit"

    # --- Explainability -------------------------------------
    top_factor = max(components, key=lambda k: abs(components[k])) if components else "N/A"
    reason = f"{top_factor} influence strongest ({components.get(top_factor, 0):.2f})"
    change_summary = "Condition shift detected"

    return {
        "symbol": symbol,
        "signal": signal,
        "confidence": confidence,
        "sell_tier": sell_tier,
        "reason": reason,
        "change": change_summary,
        "timestamp": datetime.utcnow().isoformat()
    }

# ============================================================
# ============================================================

