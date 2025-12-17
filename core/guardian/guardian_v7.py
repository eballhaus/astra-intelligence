# -*- coding: utf-8 -*-
"""
Guardian V7 — Unified System Logger & Health Monitor
----------------------------------------------------
Provides a centralized logging and self-healing interface
for Astra Intelligence. Used by all major modules.
"""

import datetime
import threading

class GuardianV7:
    """Unified guardian system for safety, logging, and state health."""
    def __init__(self):
        self._lock = threading.Lock()
        self._events = []

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


# Create a global Guardian instance and unified logger alias
guardian_log = GuardianV7()

# ============================================================
# === ASTRA GUARDIAN — Rate & Quota Monitor (v1) =============
# ============================================================
import time

_api_counters = {}

def rate_safe(api_name, interval=60, daily_limit=None):
    """Prevent overuse of the same API globally."""
    now = time.time()
    rec = _api_counters.get(api_name, {"ts": 0, "count": 0})

    if now - rec["ts"] < interval:
        guardian_log.info(f"[RateSafe] {api_name} cooldown active ({interval}s).")
        return False

    if daily_limit and rec["count"] >= daily_limit:
        guardian_log.warn(f"[RateSafe] {api_name} daily limit reached ({daily_limit}).")
        return False

    _api_counters[api_name] = {"ts": now, "count": rec["count"] + 1}
    return True

def api_usage_report():
    """Print a summary of API usage counts."""
    guardian_log.info("[Guardian] API Usage Summary:")
    for api, rec in _api_counters.items():
        guardian_log.info(f"  {api}: {rec['count']} calls today.")


# --- Patch: Add warning() compatibility if missing ---
try:
    if not hasattr(guardian_log, "warning"):
        guardian_log.warning = guardian_log.info
        guardian_log.info("[Guardian] Added .warning() alias for compatibility.")
except Exception as e:
    print("[Guardian Patch] Failed to add warning alias:", e)

# =========================================================
#  Astra Guardian — Secure API-based Live Data Access
# =========================================================
import json, requests, os

class GuardianSecureAPI:
    def __init__(self, keyfile="astra_modules/guardian/security/api_keys.json"):
        with open(keyfile, "r") as f:
            self.keys = json.load(f)
        self.alpaca_url = self.keys.get("ALPACA_BASE_URL")
        self.cg_url = self.keys.get("COINGECKO_URL")

    def fetch_stock(self, symbol="SPY", limit=500):
        headers = {
            "APCA-API-KEY-ID": self.keys.get("ALPACA_KEY"),
            "APCA-API-SECRET-KEY": self.keys.get("ALPACA_SECRET")
        }
        url = f"{self.alpaca_url}/stocks/{symbol}/bars?timeframe=1Min&limit={limit}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                print(f"[GuardianV7] ✅ Live Alpaca data for {symbol}")
                return r.json()
            print(f"[GuardianV7] ⚠️ Alpaca fetch failed ({r.status_code})")
        except Exception as e:
            print(f"[GuardianV7] ⚠️ Alpaca API error for {symbol}: {e}")
        return None

    def fetch_crypto(self, symbol="bitcoin"):
        try:
            url = f"{self.cg_url}coins/markets"
            r = requests.get(url, params={"vs_currency": "usd", "ids": symbol}, timeout=10)
            if r.status_code == 200:
                print(f"[GuardianV7] ✅ CoinGecko data for {symbol}")
                return r.json()
        except Exception as e:
            print(f"[GuardianV7] ⚠️ CoinGecko error for {symbol}: {e}")
        return None

# =========================================================
#  Astra Guardian — Multi-Provider Live Data Fetcher
# =========================================================
import os, json, requests

class GuardianSecureAPI:
    def __init__(self, keyfile="astra_modules/guardian/security/api_keys.json"):
        with open(keyfile, "r") as f:
            self.keys = json.load(f)
        self.timeout = 10

    # -----------------------------------------------
    # Stock and ETF data
    # -----------------------------------------------
    def fetch_stock(self, symbol="SPY"):
        # Try TwelveData first
        td_key = self.keys.get("TWELVEDATA_API_KEY")
        try:
            if td_key:
                url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1min&apikey={td_key}"
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    j = r.json()
                    if "values" in j:
                        print(f"[GuardianV7] ✅ Live TwelveData data for {symbol}")
                        return j
        except Exception as e:
            print(f"[GuardianV7] ⚠️ TwelveData error for {symbol}: {e}")

        # Fallback to Alpha Vantage
        av_key = self.keys.get("ALPHA_VANTAGE_API_KEY")
        try:
            if av_key:
                url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval=1min&apikey={av_key}"
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200 and "Time Series" in r.text:
                    print(f"[GuardianV7] ✅ Live Alpha Vantage data for {symbol}")
                    return r.json()
        except Exception as e:
            print(f"[GuardianV7] ⚠️ AlphaVantage error for {symbol}: {e}")

        print(f"[GuardianV7] ❌ No live stock data available for {symbol}.")
        return None

    # -----------------------------------------------
    # Crypto data (Moralis → CoinMarketCap fallback)
    # -----------------------------------------------
    def fetch_crypto(self, symbol="BTC-USD"):
        # Try Moralis first
        moralis_key = self.keys.get("MORALIS_API_KEY")
        try:
            if moralis_key:
                url = f"https://deep-index.moralis.io/api/v2/market-data/erc20/{symbol}"
                headers = {"X-API-Key": moralis_key}
                r = requests.get(url, headers=headers, timeout=self.timeout)
                if r.status_code == 200:
                    print(f"[GuardianV7] ✅ Live Moralis data for {symbol}")
                    return r.json()
        except Exception as e:
            print(f"[GuardianV7] ⚠️ Moralis error for {symbol}: {e}")

        # Fallback to CoinMarketCap
        cmc_key = self.keys.get("COINMARKETCAP_API_KEY")
        try:
            if cmc_key:
                url = f"https://pro-api.coinmarketcap.com/v1/cryptocurrency/quotes/latest?symbol={symbol.replace('-USD','')}"
                headers = {"X-CMC_PRO_API_KEY": cmc_key}
                r = requests.get(url, headers=headers, timeout=self.timeout)
                if r.status_code == 200:
                    print(f"[GuardianV7] ✅ Live CoinMarketCap data for {symbol}")
                    return r.json()
        except Exception as e:
            print(f"[GuardianV7] ⚠️ CoinMarketCap error for {symbol}: {e}")

        print(f"[GuardianV7] ❌ No live crypto data available for {symbol}.")
        return None
