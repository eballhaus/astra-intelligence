# -*- coding: utf-8 -*-
"""
Astra Intelligence — Smart Backend (v2.5a)
------------------------------------------
FastAPI backend for Astra Intelligence system.

Features:
✅ Unified data fetching from 6 API sources
✅ Automatic fallback and mock data
✅ In-memory caching with TTL
✅ Guardian quota tracking
✅ Safe JSON serialization for pandas/numpy
✅ Health check endpoint
✅ Parallel async data gathering
"""

import asyncio
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import numpy as np
import orjson
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from astra_core.guardian.guardian_v6 import guardian_log

# ===================================================================
# 🧩 Safe JSON Serialization Utility
# ===================================================================


def _json_safe_default(obj: Any) -> Any:
    """
    Universal fallback for pandas, numpy, datetime, or other exotic types.
    Ensures all objects can be serialized to JSON.

    Parameters:
        obj (Any): Object to serialize.

    Returns:
        Any: Serializable representation of the object.
    """
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if hasattr(obj, "item"):  # numpy/pandas scalars
        return obj.item()
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if pd.isna(obj):
        return None
    return str(obj)


# ===================================================================
# 🚀 FastAPI App Initialization
# ===================================================================

app = FastAPI(
    title="Astra Intelligence Backend",
    version="2.5a",
    description="Unified data API for Astra Intelligence trading system",
    default_response_class=ORJSONResponse,
)

guardian_log("[Backend] 🚀 Astra Intelligence Backend v2.5a initialized")

# ===================================================================
# 📡 Health Check Endpoint
# ===================================================================


@app.get("/v1/health")
def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for Astra backend.
    Used by client AstraAPI to verify backend availability.

    Returns:
        Dict[str, Any]: Status, service name, and timestamp.
    """
    return {
        "status": "ok",
        "service": "Astra Backend",
        "version": "2.5a",
        "timestamp": datetime.utcnow().isoformat(),
    }


# ===================================================================
# 📊 Market Overview Endpoint
# ===================================================================


@app.get("/v1/markets/overview")
async def get_market_overview(symbols: str) -> Dict[str, Any]:
    """
    Market overview endpoint showing key indices and assets.

    Example: /v1/markets/overview?symbols=BTC/USD,AAPL,^DJI

    Parameters:
        symbols (str): Comma-separated list of ticker symbols.

    Returns:
        Dict[str, Any]: Overview data with prices and changes.
    """
    try:
        syms = [s.strip().upper() for s in symbols.split(",") if s.strip()]

        if not syms:
            return {"error": "No symbols provided", "data": []}

        data = []
        for s in syms:
            # Mock data — replace with live API integration
            if "BTC" in s:
                price, change, pct_change = 45000.0, 0.25, 0.45
            elif "ETH" in s:
                price, change, pct_change = 2400.0, 0.15, 0.32
            elif "DJI" in s or "DJIA" in s:
                price, change, pct_change = 35000.0, 0.12, 0.34
            elif "GSPC" in s or "SPX" in s:
                price, change, pct_change = 4500.0, -0.05, -0.11
            else:
                price, change, pct_change = 150.0, 0.05, 0.12

            data.append(
                {
                    "symbol": s,
                    "price": price,
                    "change": change,
                    "percentChange": pct_change,
                }
            )

        guardian_log(f"[Backend] ✅ Market overview retrieved for {len(syms)} symbols")
        return {
            "data": data,
            "count": len(data),
            "source": "astra-mock",
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        guardian_log(f"[Backend] ⚠️ Market overview error: {e}")
        return {"error": str(e), "data": []}


# ===================================================================
# 🔌 ACTIVE DATA SOURCES (6 Astra API Modules)
# ===================================================================

API_MODULES: List[str] = [
    "astra_api_alphavantage",
    "astra_api_fmp",
    "astra_api_twelvedata",
    "astra_api_finnhub",
    "astra_api_eodhd",
    "astra_api_moralis",
]

# ===================================================================
# ⚙️ GLOBAL CACHE (per symbol, TTL-based)
# ===================================================================

_CACHE: Dict[str, Dict[str, Any]] = {}
_CACHE_TTL: int = 60  # seconds


def _cache_get(symbol: str) -> Optional[List[Dict[str, Any]]]:
    """
    Retrieve cached data if not expired.

    Parameters:
        symbol (str): Ticker symbol.

    Returns:
        Optional[List[Dict]]: Cached data or None if expired/missing.
    """
    try:
        entry = _CACHE.get(symbol)
        if entry and (time.time() - entry["timestamp"]) < _CACHE_TTL:
            guardian_log(f"[BackendCache] ♻️ Cache hit for {symbol}")
            return entry["data"]

        if entry:
            del _CACHE[symbol]
    except Exception as e:
        guardian_log(f"[BackendCache] ⚠️ Cache retrieval error: {e}")

    return None


def _cache_set(symbol: str, data: List[Dict[str, Any]]) -> None:
    """
    Store data in cache with timestamp.

    Parameters:
        symbol (str): Ticker symbol.
        data (List[Dict]): Data to cache.
    """
    try:
        _CACHE[symbol] = {
            "data": data,
            "timestamp": time.time(),
        }
        guardian_log(f"[BackendCache] 💾 Cached {len(data)} records for {symbol}")
    except Exception as e:
        guardian_log(f"[BackendCache] ⚠️ Cache set error: {e}")


# ===================================================================
# ⚡ ASYNC FETCH HELPERS
# ===================================================================


async def fetch_from_module(api_name: str, symbol: str) -> pd.DataFrame:
    """
    Fetch data asynchronously from one Astra API connector.
    Supports both async and sync module functions.

    Parameters:
        api_name (str): API module name.
        symbol (str): Ticker symbol.

    Returns:
        pd.DataFrame: Data from API or empty DataFrame on failure.
    """
    try:
        module = __import__(f"astra_core.apis.{api_name}", fromlist=["get_data"])

        # Prefer async version if available
        if hasattr(module, "get_data_async"):
            df = await module.get_data_async(symbol)
        elif hasattr(module, "get_data"):
            loop = asyncio.get_event_loop()
            df = await loop.run_in_executor(None, module.get_data, symbol)
        else:
            guardian_log(f"[Backend] ⚠️ {api_name} has no valid data method")
            return pd.DataFrame()

        if isinstance(df, pd.DataFrame) and not df.empty:
            df["source"] = api_name
            guardian_log(
                f"[Backend] ✅ {api_name} returned {len(df)} rows for {symbol}"
            )
            return df

        guardian_log(f"[Backend] ⚠️ {api_name} returned empty DataFrame for {symbol}")

    except Exception as e:
        guardian_log(f"[Backend] ⚠️ {api_name} fetch failed for {symbol}: {e}")

    return pd.DataFrame()


# ===================================================================
# 🌐 UNIFIED DATA ENDPOINT (v1/data/{symbol})
# ===================================================================


@app.get("/v1/data/{symbol}")
async def get_data(symbol: str) -> ORJSONResponse:
    """
    Unified Astra data endpoint with intelligent fallback.

    Fetch Strategy:
    1️⃣ Cache check (60-second TTL)
    2️⃣ AstraAPI v3.0 unified client
    3️⃣ Parallel fetch from 6 API modules
    4️⃣ Mock fallback (final resort)

    Parameters:
        symbol (str): Ticker symbol (e.g., "AAPL", "BTC/USD").

    Returns:
        ORJSONResponse: Normalized OHLCV data with source tracking.
    """
    guardian_log(f"[Backend] 🔄 Fetch request received for {symbol}")

    # ===================================================================
    # Step 1: Validate input
    # ===================================================================
    if not symbol or not isinstance(symbol, str):
        guardian_log("[Backend] ⚠️ Invalid or missing symbol parameter")
        return ORJSONResponse(
            status_code=400, content={"error": "Invalid symbol provided"}
        )

    # ===================================================================
    # Step 2: Cache check
    # ===================================================================
    cached = _cache_get(symbol)
    if cached is not None:
        guardian_log(f"[Backend] 💾 Cache hit for {symbol} ({len(cached)} records)")
        safe_json = orjson.dumps(cached, default=_json_safe_default)
        return ORJSONResponse(content=orjson.loads(safe_json))

    # ===================================================================
    # Step 3: Try AstraAPI unified client
    # ===================================================================
    try:
        from astra_core.core.api_client import AstraAPI

        guardian_log(f"[Backend] 🚀 Attempting AstraAPI v3.0 for {symbol}")
        api = AstraAPI()
        df = api.get_market_data(symbol)

        if df is not None and not df.empty:
            guardian_log(f"[Backend] ✅ AstraAPI provided {len(df)} rows for {symbol}")
            data = df.to_dict(orient="records")
            _cache_set(symbol, data)
            safe_json = orjson.dumps(data, default=_json_safe_default)
            return ORJSONResponse(content=orjson.loads(safe_json))

        guardian_log(f"[Backend] ⚠️ AstraAPI empty for {symbol}, falling back")

    except Exception as e:
        guardian_log(f"[Backend] ⚠️ AstraAPI failed: {e}")

    # ===================================================================
    # Step 4: Parallel fetch from API modules
    # ===================================================================
    guardian_log(
        f"[Backend] 🚀 Fallback: parallel fetch from {len(API_MODULES)} modules"
    )

    try:
        results = await asyncio.gather(
            *[fetch_from_module(api, symbol) for api in API_MODULES],
            return_exceptions=True,
        )
    except Exception as e:
        guardian_log(f"[Backend] 🚨 Async gather error: {e}")
        results = []

    # Filter valid DataFrames
    dfs = [r for r in results if isinstance(r, pd.DataFrame) and not r.empty]

    # ===================================================================
    # Step 5: Handle total failure — mock fallback
    # ===================================================================
    if not dfs or all(df.empty for df in dfs):
        guardian_log(
            f"[Backend] ⚠️ All sources failed for {symbol}, using mock fallback"
        )

        now = datetime.utcnow()
        dates = pd.date_range(end=now, periods=30, freq="D")
        base_price = 45000.0 if "BTC" in symbol else 150.0

        mock_df = pd.DataFrame(
            {
                "timestamp": dates,
                "open": base_price + pd.Series(range(30)).astype(float),
                "high": base_price + pd.Series(range(30)).astype(float) + 2.0,
                "low": base_price + pd.Series(range(30)).astype(float) - 2.0,
                "close": base_price + pd.Series(range(30)).astype(float) + 1.0,
                "volume": [1000 + i * 10 for i in range(30)],
                "source": "mock_fallback",
            }
        )

        data = mock_df.to_dict(orient="records")
        _cache_set(symbol, data)

        guardian_log(f"[Backend] 🧩 Mock data served for {symbol} ({len(data)} rows)")
        safe_json = orjson.dumps(data, default=_json_safe_default)
        return ORJSONResponse(content=orjson.loads(safe_json))

    # ===================================================================
    # Step 6: Merge and normalize data
    # ===================================================================
    df = pd.concat(dfs, ignore_index=True)

    # Rename columns for consistency
    rename_map = {
        "Datetime": "timestamp",
        "date": "timestamp",
        "open_price": "open",
        "close_price": "close",
        "adj_close": "close",
        "trade_price": "price",
        "last": "price",
        "vol": "volume",
    }

    df.rename(
        columns={k: v for k, v in rename_map.items() if k in df.columns}, inplace=True
    )
    df.columns = [c.lower().strip() for c in df.columns]

    # Normalize timestamp
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")

    # Fill missing OHLC columns
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = df["close"] if "close" in df.columns else np.nan

    # Derive price if missing
    if "price" not in df.columns:
        df["price"] = df["close"]

    # Clean and reset
    df = df.dropna(subset=["price"]).reset_index(drop=True)

    # ===================================================================
    # Step 7: Guardian quota tracking
    # ===================================================================
    try:
        from astra_core.guardian.guardian_v6 import guardian_log

        guardian = guardian_log()
        for api in API_MODULES:
            api_name = api.replace("astra_api_", "").upper()
            guardian.quota_monitor.record(api_name)
    except Exception as e:
        guardian_log(f"[Backend] ⚠️ Guardian quota tracking skipped: {e}")

    # ===================================================================
    # Step 8: JSON safety + cache + respond
    # ===================================================================
    try:
        # Ensure all values are JSON-serializable
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                df[col] = df[col].astype(str)
            else:
                df[col] = df[col].apply(lambda x: x.item() if hasattr(x, "item") else x)

        data = df.to_dict(orient="records")

        # Post-process for safety
        for record in data:
            for key, value in list(record.items()):
                if isinstance(value, (pd.Timestamp, datetime)):
                    record[key] = value.isoformat()
                elif pd.isna(value):
                    record[key] = None
                elif not isinstance(value, (int, float, str, bool, type(None))):
                    record[key] = str(value)

        _cache_set(symbol, data)
        guardian_log(f"[Backend] ✅ Served {len(df)} normalized records for {symbol}")

        safe_json = orjson.dumps(data, default=_json_safe_default)
        return ORJSONResponse(content=orjson.loads(safe_json))

    except Exception as e:
        guardian_log(f"[Backend] 🚨 JSON serialization error for {symbol}: {e}")
        return ORJSONResponse(
            status_code=500, content={"error": f"Serialization failed: {str(e)}"}
        )


# ===================================================================
# 🧪 Standalone Test
# ===================================================================

if __name__ == "__main__":
    import uvicorn

    guardian_log("[Backend] 🧪 Starting Astra Backend in standalone mode")
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
