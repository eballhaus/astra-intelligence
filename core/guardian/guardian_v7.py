# -*- coding: utf-8 -*-
"""
Guardian V7 — Unified System Logger & Health Monitor
----------------------------------------------------
Centralized logging, API rate monitoring, and system diagnostics
for Astra Intelligence. Fully compatible with the new API Pool.
"""

import datetime
import threading
import time
import json
import requests
from api_keys import get_available_api

# ============================================================
# === Core Guardian Logging System ===========================
# ============================================================

from core.guardian.guardian_core import GuardianLog as GuardianCore


class GuardianV7(GuardianCore):
    def fetch_live_data(self, symbols=None):
        """Unified live data fetch routed through GuardianSecureAPI."""
        from core.guardian.guardian_secure_api import GuardianSecureAPI
        secure_api = GuardianSecureAPI()
        symbols = symbols or ["AAPL", "TSLA", "NVDA", "MSFT", "GOOG"]
        now = datetime.datetime.utcnow().isoformat() + "Z"
        results = []

        for sym in symbols:
            try:
                stock_data = secure_api.fetch_stock(sym)
                price = 0.0

                if isinstance(stock_data, dict):
                    # Direct price from API
                    if "price" in stock_data:
                        price = float(stock_data["price"])
                    # Extract from nested structure (e.g., TwelveData)
                    elif "values" in stock_data and isinstance(stock_data["values"], list) and len(stock_data["values"]) > 0:
                        latest = stock_data["values"][0]
                        if "close" in latest:
                            price = float(latest["close"])
                        else:
                            price = 0.0
                    else:
                        price = 0.0

                elif isinstance(stock_data, list) and stock_data and isinstance(stock_data[0], dict):
                    # Handle list of dicts, common in API aggregates
                    first = stock_data[0]
                    price = float(first.get("close", first.get("price", 0.0)))

                results.append({
                    "symbol": sym,
                    "price": price,
                    "confidence": 80.0,
                    "grade": "A",
                    "timestamp": now,
                })
                print(f"[GuardianV7] ✅ Live data for {sym}: {price}")

            except Exception as e:
                print(f"[GuardianV7] ⚠️ Failed to fetch {sym}: {e}")
                results.append({
                    "symbol": sym,
                    "price": 0.0,
                    "confidence": 0.0,
                    "grade": "F",
                    "timestamp": now,
                })

        return results

    def log(self, level: str, message: str):
        """Record a log event."""
        with self._lock:
            entry = {
                "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                "level": level.upper(),
                "message": message,
            }
            self._events.append(entry)
            print(f"[GuardianV7] {entry['timestamp']} | {entry['level']} | {entry['message']}")

    def get_recent_events(self, limit: int = 10):
        """Return the most recent Guardian log events."""
        return self._events[-limit:]

    def info(self, message: str):
        self.log("INFO", message)

    def warning(self, message: str):
        self.log("WARN", message)

    def error(self, message: str):
        self.log("ERROR", message)


guardian_log = GuardianV7()


# ============================================================
# === Rate & Quota Control ===================================
# ============================================================

_api_counters = {}


def rate_safe(api_name, interval=60, daily_limit=None):
    """Prevent overuse of the same API globally."""
    now = time.time()
    rec = _api_counters.get(api_name, {"ts": 0, "count": 0})

    if now - rec["ts"] < interval:
        guardian_log.info(f"[RateSafe] {api_name} cooldown active ({interval}s).")
        return False

    if daily_limit and rec["count"] >= daily_limit:
        guardian_log.warning(f"[RateSafe] {api_name} daily limit reached ({daily_limit}).")
        return False

    _api_counters[api_name] = {"ts": now, "count": rec["count"] + 1}
    return True


def api_usage_report():
    """Print a summary of API usage counts."""
    guardian_log.info("[Guardian] API Usage Summary:")
    for api, rec in _api_counters.items():
        guardian_log.info(f"  {api}: {rec['count']} calls today.")


# ============================================================
# === Secure API Interface (Unified Astra Pool) ==============
# ============================================================

class GuardianSecureAPI:
    """Handles live data retrieval from Astra Unified API Pool."""

    def __init__(self):
        guardian_log.info("Initializing GuardianSecureAPI (Unified Mode)")
        self.stock_provider, self.stock_key = get_available_api("stocks")
        self.crypto_provider, self.crypto_key = get_available_api("crypto")
        self.fund_provider, self.fund_key = get_available_api("fundamentals")

    def fetch_stock(self, symbol="AAPL", limit=100):
        """Fetch stock data using Unified Astra Pool."""
        if not rate_safe("stocks", interval=5):
            return None

        guardian_log.info(f"[Guardian] Fetching stock data for {symbol} via {self.stock_provider}")
        # Stub / mock for now until integration points are set
        return {
            "symbol": symbol,
            "price": 100 + hash(symbol) % 50,
            "source": self.stock_provider,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    def fetch_crypto(self, symbol="bitcoin"):
        """Fetch crypto data using Unified Astra Pool."""
        if not rate_safe("crypto", interval=5):
            return None

        guardian_log.info(f"[Guardian] Fetching crypto data for {symbol} via {self.crypto_provider}")
        # Stub / mock data (will later call Moralis or similar)
        return {
            "symbol": symbol,
            "price_usd": 40000 + hash(symbol) % 5000,
            "source": self.crypto_provider,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }

    def fetch_fundamentals(self, symbol="AAPL"):
        """Fetch fundamentals via SimFin/Nasdaq/DataJockey."""
        if not rate_safe("fundamentals", interval=10):
            return None

        guardian_log.info(f"[Guardian] Fetching fundamentals for {symbol} via {self.fund_provider}")
        # Stub data for development phase
        return {
            "symbol": symbol,
            "pe_ratio": round(15 + hash(symbol) % 20, 2),
            "eps": round(3.5 + hash(symbol) % 2, 2),
            "source": self.fund_provider,
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }


# ============================================================
# === Compatibility & Exports ================================
# ============================================================

__all__ = ["GuardianV7", "guardian_log", "GuardianSecureAPI", "rate_safe", "api_usage_report"]
