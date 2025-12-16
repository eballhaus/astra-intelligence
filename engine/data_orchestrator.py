# -*- coding: utf-8 -*-
"""
Astra Intelligence — Data Orchestrator (Guardian v7 Integrated)
---------------------------------------------------------------
Bridges AstraAPI (multi-API client) with dashboard and agents.
"""

from core.api_client import AstraAPI
from core.guardian.guardian_v7 import GuardianV7, guardian_log
import pandas as pd
from datetime import datetime
import time


class DataOrchestrator:
    """Unified interface for live Astra data with Guardian audit logging."""

    def __init__(self):
        self.api = AstraAPI()

    def get_live_market_data(self, symbols=None):
        if symbols is None:
            symbols = ["BTC/USD", "AAPL", "SPY"]

        frames = []
        guardian_log.info(
            f"[DataOrchestrator] 🧠 Initiating live data pull for {len(symbols)} symbols."
        )

        for sym in symbols:
            start_time = time.time()
            try:
                df = self.api.get_data(sym)
                latency = round(time.time() - start_time, 3)

                if df is not None and not df.empty:
                    df["symbol"] = sym
                    df["latency_s"] = latency
                    frames.append(df)
                    guardian_log.info(
                        f"[DataOrchestrator] ✅ {sym} fetched successfully "
                        f"(rows={len(df)}, latency={latency}s)"
                    )
                else:
                    guardian_log.warning(
                        f"[DataOrchestrator] ⚠️ Empty DataFrame returned for {sym}"
                    )
            except Exception as e:
                guardian_log.error(f"[DataOrchestrator] ❌ Failed to fetch {sym}: {e}")

        if not frames:
            guardian_log.error("[DataOrchestrator] ❌ No data frames returned from any API.")
            return pd.DataFrame(
                columns=["symbol", "price", "change", "timestamp", "latency_s"]
            )

        combined = pd.concat(frames, ignore_index=True)
        combined["timestamp"] = datetime.utcnow()

        if "close" in combined.columns:
            combined["price"] = combined["close"]

        if "open" in combined.columns and "close" in combined.columns:
            try:
                combined["change"] = (
                    (combined["close"] - combined["open"]) / combined["open"]
                ) * 100
            except Exception as e:
                guardian_log.warning(f"[DataOrchestrator] ⚠️ Change% issue: {e}")
                combined["change"] = 0.0
        else:
            combined["change"] = 0.0

        for col in ["price", "change"]:
            if col in combined.columns:
                combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

        guardian_log.info(
            f"[DataOrchestrator] 🧩 Aggregation complete — {len(combined)} rows, "
            f"{combined['symbol'].nunique()} symbols."
        )
        return combined[["symbol", "price", "change", "timestamp", "latency_s"]]

def fetch_live_data(symbol: str, source_preference=None):
    """
    Unified live data fetch using prioritized APIs.
    """
    from core.guardian.guardian_v7 import guardian_log
    from utils.api_loader import load_api_key
    import pandas as pd, requests

    apis = source_preference or ["POLYGON", "ALPHAVANTAGE", "EODHD", "TWELVEDATA"]
    for api in apis:
        key = load_api_key(api)
        try:
            if api == "POLYGON":
                url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/day/2024-01-01/2024-12-15?apiKey={key}"
                resp = requests.get(url, timeout=5).json()
                df = pd.DataFrame(resp.get("results", []))
                if not df.empty:
                    guardian_log.info(f"✅ {api} data pulled for {symbol}")
                    return df
        except Exception as e:
            guardian_log.warning(f"⚠️ {api} failed for {symbol}: {e}")
    guardian_log.error("❌ All APIs failed; using synthetic fallback.")
    return pd.DataFrame()

# ============================================================
# === ASTRA SMART REFRESH ENGINE (v1) — Free Tier Safe ========
# ============================================================
import time
from datetime import datetime
from core.guardian.guardian_v7 import guardian_log
from utils.cache_manager import CacheManager  # optional if exists

# Track last API call times and quotas
API_TRACKER = {}
API_COOLDOWNS = {
    "alpha_vantage": {"interval": 3600, "daily": 25},
    "twelvedata":    {"interval": 60,   "daily": 800},
    "finnhub":       {"interval": 10,   "daily": 1000},
    "polygon":       {"interval": 60,   "daily": 300},
    "moralis":       {"interval": 30,   "daily": 400},
    "simfin":        {"interval": 600,  "daily": 300},
    "nasdaq":        {"interval": 3600, "daily": 50},
}

def _rate_safe(api_name: str) -> bool:
    """Ensures we don't exceed API cooldown or quota."""
    now = time.time()
    api = API_COOLDOWNS.get(api_name)
    if not api:
        return True
    last = API_TRACKER.get(api_name, {"ts": 0, "count": 0})
    if now - last["ts"] < api["interval"]:
        guardian_log.info(f"[RateSafe] {api_name} cooldown active ({api['interval']}s). Using cache.")
        return False
    if last["count"] >= api.get("daily", 99999):
        guardian_log.warning(f"[RateSafe] {api_name} daily quota reached ({api['daily']}). Using cache.")
        return False
    API_TRACKER[api_name] = {"ts": now, "count": last["count"] + 1}
    return True


def adaptive_refresh(symbol: str, market_state: str = "day") -> dict:
    """Dynamic refresh system balancing accuracy vs API usage."""
    from core.guardian.guardian_v7 import guardian_log

    # Determine mode intervals (seconds)
    intervals = {
        "swing": {"calm": 1800, "normal": 900, "high": 300},
        "day":   {"calm": 600,  "normal": 300, "high": 60},
    }

    # Fetch cached volatility data if available
    df = fetch_live_data(symbol)
    if df is None or df.empty:
        guardian_log.warning(f"[Adaptive] No live data for {symbol}")
        return _synthetic_fallback(symbol)

    latest = df.iloc[-1]
    vol = (latest["h"] - latest["l"]) / max(latest["c"], 0.0001)
    state = "calm" if vol < 0.005 else "high" if vol > 0.02 else "normal"

    refresh_sec = intervals[market_state][state]
    guardian_log.info(
        f"[Adaptive] {symbol}: vol={vol:.3f}, state={state}, next_refresh={refresh_sec}s"
    )

    # Smart API routing
    api_choice = "twelvedata" if market_state == "day" else "finnhub"
    if not _rate_safe(api_choice):
        cached = CacheManager.get(symbol)
        if cached:
            guardian_log.info(f"[CacheHit] Using cached data for {symbol}")
            return cached

    # Fetch and cache data
    data = fetch_live_data(symbol)
    CacheManager.set(symbol, data, ttl=refresh_sec)
    return data


# ============================================================
# === SYNTHETIC FALLBACK (v1) — Resilient Astra Mode =========
# ============================================================
import random

def _synthetic_fallback(symbol):
    """Return lightweight synthetic data if all APIs fail."""
    guardian_log.warning(f"[Fallback] Using synthetic data for {symbol}")
    import pandas as pd
    base = 100 + random.random() * 10
    df = pd.DataFrame([{
        "symbol": symbol,
        "o": base * 0.99,
        "h": base * 1.01,
        "l": base * 0.98,
        "c": base,
        "v": random.randint(1000, 5000),
        "ts": time.time()
    }])
    return df

# Patch adaptive_refresh to use fallback automatically
_old_adaptive_refresh = adaptive_refresh
def adaptive_refresh(symbol, market_state="day"):
    try:
        return _old_adaptive_refresh(symbol, market_state)
    except Exception as e:
        guardian_log.warning(f"[Adaptive] {symbol}: caught exception -> {e}")
        return _synthetic_fallback(symbol)

# ============================================================
# === CACHE-PERSISTENT SYNTHETIC FALLBACK (v2) ===============
# ============================================================
from utils.cache_manager import CacheManager

def _synthetic_fallback(symbol):
    """Return lightweight synthetic data if all APIs fail, cached for 10 minutes."""
    guardian_log.warning(f"[Fallback] Using synthetic data for {symbol} (cached 10m)")
    import pandas as pd, random
    cached = CacheManager.get(symbol)
    if cached is not None:
        guardian_log.info(f"[Fallback] Serving cached synthetic data for {symbol}")
        return cached

    base = 100 + random.random() * 10
    df = pd.DataFrame([{
        "symbol": symbol,
        "o": base * 0.99,
        "h": base * 1.01,
        "l": base * 0.98,
        "c": base,
        "v": random.randint(1000, 5000),
        "ts": time.time()
    }])

    CacheManager.set(symbol, df, ttl=600)
    guardian_log.info(f"[Fallback] Cached synthetic data for {symbol} (600s TTL)")
    return df
