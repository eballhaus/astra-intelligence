"""Astra Intelligence Unified Data Loader — Phase 94b (Guardian Safe + Visual Test)"""
import pandas as pd
import random
from datetime import datetime, timedelta
from core.cache_manager import CacheManager
from utils.guardian_lazy import get_guardian
from engine.astra_prime import get_top_signals

def load_data(symbol="SPX"):
    cache = CacheManager()
    guardian = get_guardian()
    try:
        from fetch_core.fetch_unified import load_dashboard_data as api_loader
        data = api_loader(symbol)
        if data and "history" in data:
                top = get_top_signals(limit=6)
    data["top_signals"] = top
    return data
    except Exception as e:
        if guardian and hasattr(guardian, "log"):
            guardian.log(f"[DashboardData] ⚠️ Live load failed: {e}")
    try:
        data = cache.get_last("dashboard_data")
        if data and "history" in data:
                top = get_top_signals(limit=6)
    data["top_signals"] = top
    return data
    except Exception:
        pass
    now = datetime.utcnow()
    times = [now - timedelta(hours=i) for i in range(50)][::-1]
    prices = [4800 + random.uniform(-30, 30) for _ in times]
    df = pd.DataFrame({
        "time": times,
        "open": [p - random.uniform(0, 5) for p in prices],
        "high": [p + random.uniform(0, 8) for p in prices],
        "low":  [p - random.uniform(0, 8) for p in prices],
        "close":[p + random.uniform(-4, 4) for p in prices],
    })
    data = {
        "symbol": symbol,
        "price": round(df["close"].iloc[-1], 2),
        "change_pct": round(random.uniform(-1.5, 1.5), 2),
        "trend": random.choice(["Bullish", "Bearish", "Neutral"]),
        "volatility": random.choice(["Low", "Medium", "High"]),
        "confidence": random.randint(60, 95),
        "history": df.to_dict(orient="records"),
    }
    if guardian and hasattr(guardian, "log"):
        guardian.log("[DashboardData] Using fallback demo data for dashboard display.")
        top = get_top_signals(limit=6)
    data["top_signals"] = top
    return data
