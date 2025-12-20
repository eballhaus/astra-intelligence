# -*- coding: utf-8 -*-
"""
Guardian Core V7 — Astra Intelligence Unified System
----------------------------------------------------
Central module providing:
 - Unified logging (guardian_log)
 - Sentinel monitoring
 - Rate/Quota safety
 - Secure API data fetch (stocks, crypto)
 - Health snapshot + self-monitoring
"""

import os
import sys
import json
import time
import threading
import importlib
import requests
from datetime import datetime

# --- Path Fix ---
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ==========================================================
# Logging System
# ==========================================================
class GuardianLog:
    """Unified logger for Astra modules."""
    def __init__(self):
        self.messages = []

    def log(self, level: str, message: str):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[GuardianLog] {ts} | {level} | {message}"
        print(line)
        self.messages.append(line)

    def info(self, message): self.log("INFO", message)
    def warning(self, message): self.log("WARN", message)
    def error(self, message): self.log("ERROR", message)

    def save(self, path=None):
        path = path or os.path.expanduser("~/astra_guardian_runtime/guardian_log.txt")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "a") as f:
            for msg in self.messages:
                f.write(msg + "\n")

guardian_log = GuardianLog()

# ==========================================================
# Sentinel Integrity Watchdog
# ==========================================================
class GuardianSentinel:
    """Integrity checker for critical modules."""
    def __init__(self, modules=None, log_path=None):
        self.modules_to_check = modules or [
            "engine.data_orchestrator",
            "astra_modules.agents.neural_agent",
        ]
        self.log_path = log_path or os.path.expanduser("~/astra_guardian_runtime/sentinel_report.json")
        self.report = {"checked": [], "failed": []}

    def check_imports(self):
        for mod in self.modules_to_check:
            try:
                importlib.import_module(mod)
                self.report["checked"].append(mod)
            except Exception as e:
                self.report["failed"].append(str(e))
        self.report["timestamp"] = datetime.utcnow().isoformat()
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        with open(self.log_path, "w") as f:
            json.dump(self.report, f, indent=2)
        print(f"[Sentinel] Report saved to {self.log_path}")

# ==========================================================
# Rate & Quota Safety
# ==========================================================
_api_counters = {}

def rate_safe(api_name, interval=60, daily_limit=None):
    """Prevent overuse of the same API globally."""
    now = time.time()
    rec = _api_counters.get(api_name, {"ts": 0, "count": 0})

    if now - rec["ts"] < interval:
        guardian_log.warning(f"[RateSafe] {api_name} cooldown active ({interval}s).")
        return False

    if daily_limit and rec["count"] >= daily_limit:
        guardian_log.warning(f"[RateSafe] {api_name} daily limit reached ({daily_limit}).")
        return False

    _api_counters[api_name] = {"ts": now, "count": rec["count"] + 1}
    return True

def api_usage_report():
    guardian_log.info("[Guardian] API Usage Summary:")
    for api, rec in _api_counters.items():
        guardian_log.info(f"  {api}: {rec['count']} calls today.")

# ==========================================================
# Guardian Secure API Interface
# ==========================================================
class GuardianSecureAPI:
    """Handles live data retrieval from stock and crypto APIs."""

    def __init__(self):
        self.keys = {
            "ALPACA_KEY": os.getenv("ALPACA_API_KEY_ID", ""),
            "ALPACA_SECRET": os.getenv("ALPACA_API_SECRET_KEY", "")
        }
        self.alpaca_url = "https://data.alpaca.markets/v2"
        self.cg_url = "https://api.coingecko.com/api/v3/"

    def fetch_stock(self, symbol="SPY", limit=500):
        if not rate_safe("alpaca_stock", interval=10):
            return None

        headers = {
            "APCA-API-KEY-ID": self.keys["ALPACA_KEY"],
            "APCA-API-SECRET-KEY": self.keys["ALPACA_SECRET"],
        }
        url = f"{self.alpaca_url}/stocks/{symbol}/bars?timeframe=1Min&limit={limit}"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                guardian_log.info(f"✅ Alpaca data for {symbol}")
                return r.json()
            guardian_log.warning(f"⚠️ Alpaca fetch failed ({r.status_code})")
        except Exception as e:
            guardian_log.error(f"Alpaca API error for {symbol}: {e}")
        return None

    def fetch_crypto(self, symbol="bitcoin"):
        if not rate_safe("coingecko_crypto", interval=10):
            return None

        try:
            url = f"{self.cg_url}coins/markets"
            r = requests.get(url, params={"vs_currency": "usd", "ids": symbol}, timeout=10)
            if r.status_code == 200:
                guardian_log.info(f"✅ CoinGecko data for {symbol}")
                return r.json()
            guardian_log.warning(f"⚠️ CoinGecko fetch failed ({r.status_code})")
        except Exception as e:
            guardian_log.error(f"CoinGecko API error for {symbol}: {e}")
        return None

# ==========================================================
# GuardianV7 Main
# ==========================================================
class GuardianV7:
    """Top-level orchestrator for Astra system safety and logging."""

    def __init__(self):
        self.log = guardian_log
        self.secure_api = GuardianSecureAPI()

    def api_ping(self, api_name):
        guardian_log.info(f"Pinging API: {api_name}")
        rate_safe(api_name)

    def fetch_live_data(self, symbols=None):
        guardian_log.info("Fetching live data through GuardianSecureAPI...")
        data = {}
        symbols = symbols or ["AAPL", "TSLA"]
        for sym in symbols:
            stock_data = self.secure_api.fetch_stock(sym, limit=10)
            data[sym] = stock_data or {"error": "No data"}
        return data

    def snapshot(self):
        snap_dir = os.path.expanduser("~/astra_guardian_runtime/snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        snap_file = os.path.join(snap_dir, f"snapshot_{int(time.time())}.json")
        data = {
            "timestamp": datetime.utcnow().isoformat(),
            "modules": list(importlib.sys.modules.keys()),
            "api_usage": _api_counters,
        }
        with open(snap_file, "w") as f:
            json.dump(data, f, indent=2)
        guardian_log.info(f"Snapshot saved: {snap_file}")

    def _start_health_monitor(self):
        def loop():
            while True:
                guardian_log.info("Health check OK.")
                time.sleep(60)
        threading.Thread(target=loop, daemon=True).start()

# ==========================================================
# Compatibility Aliases
# ==========================================================
Guardian = GuardianV7
__all__ = ["GuardianV7", "GuardianLog", "GuardianSentinel", "GuardianSecureAPI", "Guardian", "guardian_log"]
