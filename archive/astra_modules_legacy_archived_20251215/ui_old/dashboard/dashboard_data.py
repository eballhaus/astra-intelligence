# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Data Loader (v2.4 LiveFix Guardian+Async Safe)
----------------------------------------------------------------------------
Unified data loader using Astra internal APIs with complete fallback chain.

🧠 Features:
✅ Uses AstraAPI + internal backend only (no external feeds)
✅ Predictive + synthetic fallback chain
✅ Guardian-integrated logging
✅ Smart caching + freshness validation
✅ Live mode + UTC-aware timestamps
✅ Async-safe backend handler for Streamlit event loops
"""

import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd

from astra_core.guardian.guardian_v6 import guardian

# ===================================================================
# ⚙️ Configuration
# ===================================================================

CACHE_DIR = "/tmp/astra_cache"
STATE_CACHE_PATH = os.path.join(CACHE_DIR, "astra_state_cache.json")
DATA_FRESHNESS_THRESHOLD = 300  # 5 minutes
BACKEND_URL = os.getenv("ASTRA_BACKEND_URL", "http://127.0.0.1:8000")

os.makedirs(CACHE_DIR, exist_ok=True)


# ===================================================================
# 💾 Cache Management
# ===================================================================


def load_cached_data(symbol: str) -> Optional[pd.DataFrame]:
    """Load locally cached data if available."""
    try:
        cache_path = os.path.join(CACHE_DIR, f"data_{symbol.replace('/', '_')}.csv")
        if not os.path.exists(cache_path):
            return None
        df = pd.read_csv(cache_path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        guardian.log(f"[Cache] 💾 Loaded cached {symbol} ({len(df)} rows)")
        return df
    except Exception as e:
        guardian.log(f"[Cache] ⚠️ Load error for {symbol}: {e}")
        return None


def save_cache(df: pd.DataFrame, symbol: str) -> None:
    """Save dataframe to cache."""
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        cache_path = os.path.join(CACHE_DIR, f"data_{symbol.replace('/', '_')}.csv")
        df.to_csv(cache_path, index=False)
        guardian.log(f"[Cache] ✅ Saved {symbol} ({len(df)} rows)")
    except Exception as e:
        guardian.log(f"[Cache] ⚠️ Save error for {symbol}: {e}")


# ===================================================================
# 🔗 AstraAPI Integration (LIVE Data Enabled)
# ===================================================================


def fetch_from_astra_api(symbol: str) -> Optional[pd.DataFrame]:
    """
    Use AstraAPI to fetch REAL market data (live API-first).
    Falls back gracefully to synthetic or cached sources if needed.
    """
    try:
        # import the primary AstraAPI (which should now call your live feed)
        from astra_core.core.api_client import AstraAPI

        api = AstraAPI()

        # attempt live retrieval
        df = api.get_data(symbol)
        if df is not None and not df.empty:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df.attrs = {
                "source": df.attrs.get("source", "my_api_live"),
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc),
                "price": float(df["close"].iloc[-1]) if "close" in df.columns else None,
                "data_fresh": True,
                "confidence": df.attrs.get("confidence", 0.99),
            }
            guardian.log(
                f"[AstraAPI] ✅ LIVE data loaded for {symbol} ({df.attrs['source']})"
            )
            save_cache(df, symbol)
            return df

        guardian.log(
            f"[AstraAPI] ⚠️ No live data returned for {symbol}, fallback triggered."
        )

    except Exception as e:
        guardian.log(f"[AstraAPI] ⚠️ Live data error for {symbol}: {e}")

    # fallback chain
    cached = load_cached_data(symbol)
    if cached is not None:
        guardian.log(f"[AstraAPI] 🔁 Using cached data for {symbol}")
        return cached

    try:
        from astra_core.scanners.synthetic_generator import generate_synthetic_data

        guardian.log(f"[AstraAPI] 🧪 Generating synthetic fallback for {symbol}")
        return generate_synthetic_data(symbol)
    except Exception as e:
        guardian.log(f"[AstraAPI] ❌ Failed fallback for {symbol}: {e}")
        return None


# ===================================================================
# 🌐 Backend Fallback (Async + Safe Wrapper)
# ===================================================================


async def fetch_from_backend_async(symbol: str) -> Optional[pd.DataFrame]:
    """Fetch data from internal Astra backend (http://127.0.0.1:8000)."""
    try:
        url = f"{BACKEND_URL}/v1/data/{symbol}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and "data" in data:
                df = pd.DataFrame(data["data"])
            else:
                df = pd.DataFrame(data)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df.attrs = {"source": "backend", "timestamp": datetime.now(timezone.utc)}
            guardian.log(f"[Backend] ✅ Received {len(df)} rows for {symbol}")
            return df
    except Exception as e:
        guardian.log(f"[Backend] ⚠️ Fallback failed for {symbol}: {e}")
        return None


def fetch_from_backend(symbol: str) -> Optional[pd.DataFrame]:
    """Async-safe backend wrapper that works in Streamlit environments."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            guardian.log(
                f"[Backend] ⚙️ Event loop active — scheduling backend fetch for {symbol}"
            )
            import nest_asyncio

            nest_asyncio.apply()
            return loop.run_until_complete(fetch_from_backend_async(symbol))
        else:
            return asyncio.run(fetch_from_backend_async(symbol))
    except Exception as e:
        guardian.log(f"[Backend] ⚠️ Sync fallback failed for {symbol}: {e}")
        return None


# ===================================================================
# 🔮 Predictive + Synthetic Fallback
# ===================================================================


def get_predictive_forecast(symbol: str) -> Optional[pd.DataFrame]:
    """Predictive fallback using Astra's forecast engine."""
    try:
        from astra_core.forecast.predictive_engine import HybridScan

        scan = HybridScan()
        forecast = scan.predict(symbol)
        if forecast and isinstance(forecast, (list, tuple)) and len(forecast) >= 2:
            price, delta = float(forecast[0]), float(forecast[1])
            guardian.log(f"[Forecast] 🔮 {symbol} → {price:.2f} ({delta:+.2f})")
            now = datetime.now(timezone.utc)
            df = pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "open": price * 0.995,
                        "high": price * 1.005,
                        "low": price * 0.995,
                        "close": price,
                        "volume": 1000,
                    }
                ]
            )
            df.attrs = {"source": "forecast", "timestamp": now}
            return df
    except Exception as e:
        guardian.log(f"[Forecast] ⚠️ Predictive fallback failed: {e}")
    return None


def generate_synthetic_data(symbol: str) -> pd.DataFrame:
    """Last-resort synthetic generator."""
    import random

    guardian.log(f"[Synthetic] ⚙️ Generating synthetic data for {symbol}")
    now = datetime.now(timezone.utc)
    df = pd.DataFrame(
        [
            {
                "timestamp": now,
                "open": random.uniform(50, 200),
                "high": random.uniform(50, 200),
                "low": random.uniform(50, 200),
                "close": random.uniform(50, 200),
                "volume": random.randint(1000, 10000),
            }
            for _ in range(30)
        ]
    )
    df.attrs = {"source": "synthetic", "timestamp": now}
    return df


# ===================================================================
# ✅ Unified Load Function
# ===================================================================


def load_data(symbol: str = "AAPL") -> pd.DataFrame:
    """Unified Astra data loader with full fallback chain."""
    guardian.log(f"[DashboardData] 🚀 Loading {symbol}")

    # 1️⃣ AstraAPI
    df = fetch_from_astra_api(symbol)
    if df is not None and not df.empty:
        save_cache(df, symbol)
        return df

    # 2️⃣ Backend
    df = fetch_from_backend(symbol)
    if df is not None and not df.empty:
        save_cache(df, symbol)
        return df

    # 3️⃣ Cache
    df = load_cached_data(symbol)
    if df is not None and not df.empty:
        df.attrs = {"source": "cache", "timestamp": datetime.now(timezone.utc)}
        guardian.log(f"[DashboardData] 💾 Using cached data for {symbol}")
        return df

    # 4️⃣ Predictive
    df = get_predictive_forecast(symbol)
    if df is not None and not df.empty:
        return df

    # 5️⃣ Synthetic (always works)
    df = generate_synthetic_data(symbol)
    guardian.log(f"[DashboardData] ✅ Synthetic fallback used for {symbol}")

    # 🔧 Ensure minimal dataframe integrity
    required_cols = ["timestamp", "open", "high", "low", "close", "volume"]
    for col in required_cols:
        if col not in df.columns:
            guardian.log(f"[DashboardData] 🔧 Adding missing column: {col}")
            if col == "timestamp":
                df[col] = datetime.now(timezone.utc)
            elif col == "volume":
                df[col] = 1000
            else:
                df[col] = 100.0

    if "close" not in df.columns or df["close"].isnull().all():
        guardian.log("[DashboardData] 🔧 Creating close price column")
        df["close"] = 100.0

    df.dropna(subset=["close"], inplace=True)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df["timestamp"].fillna(datetime.now(timezone.utc), inplace=True)

    guardian.log(
        f"[DashboardData] ✅ Final dataframe for {symbol} "
        f"from source: {df.attrs.get('source', 'unknown')} "
        f"({len(df)} rows, columns: {list(df.columns)})"
    )
    return df


# -------------------------------------------------------------------
# 🕒 Legacy Compatibility: validate_data_freshness
# -------------------------------------------------------------------
def validate_data_freshness(df: pd.DataFrame, symbol: str) -> bool:
    """Backward-compatible stub for dashboard_cards."""
    try:
        if df is None or df.empty or "timestamp" not in df.columns:
            return False
        last = pd.to_datetime(df["timestamp"].max(), utc=True, errors="coerce")
        age = (datetime.now(timezone.utc) - last).total_seconds()
        guardian.log(f"[Compat] ⏱️ {symbol} data age: {age:.1f}s")
        return age <= DATA_FRESHNESS_THRESHOLD
    except Exception as e:
        guardian.log(f"[Compat] ⚠️ Freshness check failed for {symbol}: {e}")
        return False


# ===================================================================
# 🧪 Self-test
# ===================================================================
if __name__ == "__main__":
    guardian.log("[DashboardData] 🔍 Self-test started")
    for sym in ["AAPL", "BTC/USD", "TSLA"]:
        df = load_data(sym)
        print(f"{sym}: {len(df)} rows from {df.attrs.get('source')}")
        print(f"  Columns: {list(df.columns)}")
        print(
            f"  Sample close: {df['close'].iloc[0] if 'close' in df.columns else 'MISSING'}"
        )
