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
    import requests
    import pandas as pd
    API_URL = "http://127.0.0.1:8000"
    def load_data(symbol="AAPL"):
        try:
            r = requests.get(f"{API_URL}/v1/data/{symbol}", timeout=5)
            if r.status_code != 200:
                print(f"[DashboardData] ⚠️ API returned {r.status_code}")
                return pd.DataFrame()
            data = r.json().get("data", [])
            df = pd.DataFrame(data)
            print(f"[DashboardData] ✅ Loaded {len(df)} rows for {symbol}")
            return df
        except Exception as e:
            print(f"[DashboardData] ❌ Failed to load {symbol}: {e}")
            return pd.DataFrame()
