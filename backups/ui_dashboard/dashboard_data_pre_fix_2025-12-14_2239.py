# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Data Loader (v2.4 LiveFix Guardian+Async Safe)
---------------------------------------------------------------------------
Unified data loader using Astra internal APIs with complete fallback chain.
"""
import asyncio, os, httpx, pandas as pd
from datetime import datetime, timezone
from typing import Optional
from astra_core.guardian.guardian_v6 import guardian

CACHE_DIR = "/tmp/astra_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

def load_cached_data(symbol: str) -> Optional[pd.DataFrame]:
    try:
        path = os.path.join(CACHE_DIR, f"data_{symbol.replace('/', '_')}.csv")
        if not os.path.exists(path): return None
        df = pd.read_csv(path)
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        print(f"[Cache] 💾 Loaded cached {symbol} ({len(df)} rows)")
        return df
    except Exception as e:
        print(f"[Cache] ⚠️ Load error for {symbol}: {e}")
        return None

def save_cache(df: pd.DataFrame, symbol: str):
    try:
        path = os.path.join(CACHE_DIR, f"data_{symbol.replace('/', '_')}.csv")
        df.to_csv(path, index=False)
        print(f"[Cache] ✅ Saved {symbol} ({len(df)} rows)")
    except Exception as e:
        print(f"[Cache] ⚠️ Save error for {symbol}: {e}")

# simplified unified loader
def load_data(symbol: str = "AAPL") -> pd.DataFrame:
    print(f"[DashboardData] 🚀 Loading {symbol}")
    try:
        from core.api_client import AstraAPI
        api = AstraAPI()
        df = api.get_data(symbol)
        if df is not None and not df.empty:
            save_cache(df, symbol)
            return df
    except Exception as e:
        print(f"[DashboardData] ⚠️ Live fetch failed: {e}")

    df = load_cached_data(symbol)
    if df is not None and not df.empty:
        print(f"[DashboardData] 💾 Using cached data for {symbol}")
        return df

    print(f"[DashboardData] 🧪 Generating synthetic fallback for {symbol}")
    import random
    now = datetime.now(timezone.utc)
    df = pd.DataFrame(
        [{"timestamp": now, "open": 100, "high": 105, "low": 95,
          "close": random.uniform(90,110), "volume": 1000}]
    )
    df.attrs = {"source": "synthetic"}
    return df

