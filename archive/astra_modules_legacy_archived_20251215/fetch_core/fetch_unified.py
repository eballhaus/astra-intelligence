# -*- coding: utf-8 -*-
"""
Astra Intelligence — Unified Fetch Core (v3.8 Hybrid-LiveFix)
--------------------------------------------------------------
✅ Primary Astra-native data flow
✅ Integrates Astra API + optional external fallback (Binance / Yahoo)
✅ Predictive fallback when Astra or live API unavailable
✅ Guardian-protected with structured logs
✅ UTC-safe timestamps and caching
"""

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, Optional

import pandas as pd
import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from core.guardian.guardian_v6 import guardian

# ============================================================
# 🌐 CONFIGURATION
# ============================================================

ASTRA_API_BASE = os.getenv("ASTRA_API_BASE", "https://api.astra-intelligence.com/v1")
API_KEY = os.getenv("ASTRA_API_KEY", "YOUR_API_KEY_HERE")

CACHE_DIR = os.path.expanduser("~/astra_guardian_runtime/cache")
os.makedirs(CACHE_DIR, exist_ok=True)

CACHE_MAX_AGE = {
    "realtime": 60,
    "market_overview": 120,
    "crypto": 120,
    "daily": 300,
}

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Accept": "application/json",
    "User-Agent": "AstraIntelligence/3.8",
}

# ============================================================
# 📦 DATA STRUCTURE
# ============================================================


@dataclass
class MarketData:
    symbol: str
    price: float
    change: float
    change_percent: float
    volume: Optional[int] = None
    timestamp: Optional[datetime] = None
    source: str = "astra_api"
    is_fresh: bool = False


# ============================================================
# 🔧 UTILITY FUNCTIONS
# ============================================================

_session = None


def get_session() -> requests.Session:
    """Return a persistent session with retry logic."""
    global _session
    if _session is None:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        _session = session
    return _session


def is_market_hours() -> bool:
    """Return True if within US extended trading hours."""
    try:
        eastern = pytz.timezone("US/Eastern")
        now_et = datetime.now(eastern)
        if now_et.weekday() >= 5:
            return False
        pre_open = now_et.replace(hour=7, minute=0, second=0, microsecond=0)
        after_close = now_et.replace(hour=20, minute=0, second=0, microsecond=0)
        return pre_open <= now_et <= after_close
    except Exception:
        return True


def validate_data_freshness(
    timestamp: Optional[datetime], max_age_seconds: int = 300
) -> bool:
    """Check if timestamp is within freshness range."""
    if not timestamp:
        return False
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - timestamp).total_seconds()
    return age <= max_age_seconds


# ============================================================
# 🌍 API WRAPPER
# ============================================================


def api_get(
    endpoint: str,
    params: dict = None,
    cache_key: str = None,
    ttl: int = 60,
    force_refresh: bool = False,
) -> Dict:
    """Generic GET with caching and retry."""
    cache_file = None
    if cache_key:
        cache_file = os.path.join(CACHE_DIR, f"{cache_key}.json")

    if cache_file and not force_refresh and os.path.exists(cache_file):
        age = time.time() - os.path.getmtime(cache_file)
        if age < ttl:
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                guardian.log(f"[Fetch] 💾 Cached {cache_key} used ({int(age)}s old)")
                return data
            except Exception as e:
                guardian.log(f"[Fetch] ⚠️ Cache read failed for {cache_key}: {e}")

    try:
        url = f"{ASTRA_API_BASE}/{endpoint.lstrip('/')}"
        session = get_session()
        response = session.get(url, headers=HEADERS, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data["_metadata"] = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "astra_api",
                "endpoint": endpoint,
            }
        if cache_file:
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, default=str)
        guardian.log(f"[Fetch] ✅ GET {endpoint} succeeded")
        return data
    except Exception as e:
        guardian.log(f"[Fetch] 🚨 Astra API request failed ({endpoint}): {e}")
        return {}


# ============================================================
# 📈 LIVE QUOTES
# ============================================================


def fetch_live_quote(symbol: str) -> Optional[MarketData]:
    """Fetch live quote, with Astra → Binance/Yahoo fallback."""
    try:
        data = api_get(
            f"markets/quote/{symbol}",
            params={"realtime": "true"},
            cache_key=f"quote_{symbol}",
            ttl=30,
            force_refresh=is_market_hours(),
        )
        if data and "price" in data:
            ts = datetime.fromisoformat(
                data.get("timestamp", datetime.now(timezone.utc).isoformat())
            )
            quote = MarketData(
                symbol=symbol,
                price=float(data.get("price", 0)),
                change=float(data.get("change", 0)),
                change_percent=float(data.get("change_percent", 0)),
                volume=data.get("volume"),
                timestamp=ts,
                source="astra_api_live",
                is_fresh=validate_data_freshness(ts, 300),
            )
            guardian.log(f"[Fetch] ✅ Live Astra quote {symbol} ${quote.price:.2f}")
            return quote
    except Exception as e:
        guardian.log(f"[Fetch] ⚠️ Astra live quote failed: {e}")

    # External live fallback (Binance/Yahoo)
    try:
        if "/" in symbol or "-" in symbol:
            # Crypto from Binance
            mapped = symbol.replace("/", "").upper()
            resp = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                params={"symbol": mapped},
                timeout=5,
            )
            resp.raise_for_status()
            price = float(resp.json().get("price", 0))
            guardian.log(f"[Fetch] 🌐 Binance fallback {symbol}: ${price:.2f}")
            return MarketData(
                symbol=symbol,
                price=price,
                change=0,
                change_percent=0,
                timestamp=datetime.now(timezone.utc),
                source="binance_fallback",
                is_fresh=True,
            )
        else:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period="1d", interval="1m")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                guardian.log(f"[Fetch] 🌐 Yahoo fallback {symbol}: ${price:.2f}")
                return MarketData(
                    symbol=symbol,
                    price=price,
                    change=0,
                    change_percent=0,
                    timestamp=datetime.now(timezone.utc),
                    source="yfinance_fallback",
                    is_fresh=True,
                )
    except Exception as ext_err:
        guardian.log(f"[Fetch] ⚠️ External fallback failed: {ext_err}")

    # Predictive fallback
    try:
        from core.forecast.predictive_engine import HybridScan

        forecast = HybridScan().predict(symbol)
        if forecast and len(forecast) >= 2:
            price, delta = forecast[0], forecast[1]
            guardian.log(f"[Fetch] 🔮 Predictive fallback used for {symbol}")
            return MarketData(
                symbol=symbol,
                price=price,
                change=delta,
                change_percent=round((delta / price) * 100, 2) if price else 0,
                timestamp=datetime.now(timezone.utc),
                source="astra_forecast",
                is_fresh=True,
            )
    except Exception as f_err:
        guardian.log(f"[Fetch] ⚠️ Predictive fallback unavailable: {f_err}")

    return None


# ============================================================
# 💹 SYMBOL DATA
# ============================================================


def get_symbol_data(
    symbol: str, period: str = "1d", interval: str = "1m"
) -> pd.DataFrame:
    """Unified Astra symbol data with external and predictive fallback."""
    guardian.log(f"[Fetch] 📊 Fetching {symbol} (period={period}, interval={interval})")
    try:
        data = api_get(
            f"markets/symbols/{symbol}/history",
            params={"period": period, "interval": interval},
            cache_key=f"symbol_{symbol}_{period}_{interval}",
            ttl=CACHE_MAX_AGE["realtime" if period == "1d" else "daily"],
        )
        candles = data.get("candles") or data.get("data") or []
        if not candles:
            raise ValueError("No Astra data returned")

        df = pd.DataFrame(candles)
        rename = {
            "t": "timestamp",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
        df.rename(
            columns={k: v for k, v in rename.items() if k in df.columns}, inplace=True
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df[["timestamp", "open", "high", "low", "close", "volume"]]
        df.attrs = {
            "source": "astra_api",
            "symbol": symbol,
            "timestamp": datetime.now(timezone.utc),
        }
        guardian.log(f"[Fetch] ✅ Loaded {len(df)} bars for {symbol}")
        return df
    except Exception as e:
        guardian.log(f"[Fetch] ⚠️ Astra history unavailable for {symbol}: {e}")

    # --- External fallback if Astra fails ---
    try:
        if "/" in symbol or "-" in symbol:
            # Binance fallback for crypto
            mapped = symbol.replace("/", "").upper()
            url = "https://api.binance.com/api/v3/klines"
            params = {"symbol": mapped, "interval": "1h", "limit": 50}
            resp = requests.get(url, params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            df = pd.DataFrame(
                [
                    {
                        "timestamp": datetime.utcfromtimestamp(x[0] / 1000).replace(
                            tzinfo=timezone.utc
                        ),
                        "open": float(x[1]),
                        "high": float(x[2]),
                        "low": float(x[3]),
                        "close": float(x[4]),
                        "volume": float(x[5]),
                    }
                    for x in data
                ]
            )
            df.attrs = {
                "source": "binance",
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc),
            }
            guardian.log(f"[Fetch] 🌐 Binance fallback used for {symbol}")
            return df
        else:
            import yfinance as yf

            hist = yf.download(symbol, period=period, interval=interval)
            hist.reset_index(inplace=True)
            hist.rename(columns={"Datetime": "timestamp"}, inplace=True)
            hist["timestamp"] = pd.to_datetime(hist["timestamp"], utc=True)
            df = hist[["timestamp", "Open", "High", "Low", "Close", "Volume"]].rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            df.attrs = {
                "source": "yfinance",
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc),
            }
            guardian.log(f"[Fetch] 🌐 Yahoo fallback used for {symbol}")
            return df
    except Exception as ext_f_err:
        guardian.log(
            f"[Fetch] ⚠️ External data fallback failed for {symbol}: {ext_f_err}"
        )

    # --- Predictive fallback ---
    try:
        from core.forecast.predictive_engine import HybridScan

        forecast = HybridScan().predict(symbol)
        if forecast and len(forecast) >= 2:
            price, change = forecast[0], forecast[1]
            df = pd.DataFrame(
                [
                    {
                        "timestamp": datetime.now(timezone.utc),
                        "open": price * 0.995,
                        "high": price * 1.005,
                        "low": price * 0.995,
                        "close": price,
                        "volume": 0,
                    }
                ]
            )
            df.attrs = {
                "source": "astra_forecast",
                "symbol": symbol,
                "timestamp": datetime.now(timezone.utc),
            }
            guardian.log(f"[Fetch] 🔮 Predictive fallback generated for {symbol}")
            return df
    except Exception as pred_err:
        guardian.log(f"[Fetch] ⚠️ Forecast fallback failed for {symbol}: {pred_err}")

    # --- Last resort empty frame ---
    df = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df.attrs = {
        "source": "error",
        "symbol": symbol,
        "timestamp": datetime.now(timezone.utc),
    }
    guardian.log(
        f"[Fetch] 🚨 No data available for {symbol}, returning empty DataFrame"
    )
    return df
