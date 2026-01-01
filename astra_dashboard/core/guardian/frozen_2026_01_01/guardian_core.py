import sys, os
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.append(PROJECT_ROOT)

"""
GuardianV7 — Astra Intelligence Core Guardian
Full Hybrid Version (Core + Sentinel + Logging)
"""

import json
import time
import threading
import importlib
import datetime
import requests
from datetime import datetime

ratewatch = importlib.import_module("guardian.guardian_ratewatch")

# ==========================================================
# Logging System (from old guardian_log)
# ==========================================================
class guardian_log:
    def __init__(self, *args, **kwargs):
        self.messages = []

    def log(self, message):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[GuardianLog] {ts} | {message}"
        print(line)
        self.messages.append(line)

    def save(self, path=None):
        try:
            path = path or os.path.expanduser("~/astra_guardian_runtime/guardian_log.txt")
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                for msg in self.messages:
                    f.write(msg + "\n")
        except Exception as e:
            print(f"[GuardianCompat] ⚠️ Failed to save logs: {e}")


# ==========================================================
# Sentinel Integrity Watchdog (from GuardianSentinel)
# ==========================================================
class GuardianSentinel:
    def __init__(self, base_path=None, modules_to_check=None):
        self.base_path = base_path or os.getcwd()
        self.modules_to_check = modules_to_check or [
            "guardian.guardian_v6",
            "guardian.environment_guardian",
            "engine",
            "fetch_core",
        ]
        self.log_path = os.path.join(self.base_path, "sentinel_report.json")
        self.report = {"checked": [], "failed": [], "timestamp": None}

    def check_imports(self):
        import importlib
        for mod in self.modules_to_check:
            try:
                importlib.import_module(mod)
                self.report["checked"].append(mod)
            except Exception as e:
                self.report["failed"].append(str(e))
        self.report["timestamp"] = datetime.utcnow().isoformat()
        with open(self.log_path, "w") as f:
            json.dump(self.report, f, indent=2)
        print(f"[Sentinel] Report saved to {self.log_path}")


# ==========================================================
# GuardianV7 Main
# ==========================================================
class GuardianV7:
    """Unified guardian system for safety, logging, and state health."""

    def __init__(self, *args, **kwargs):
        self._lock = threading.Lock()
        self._events = []

    def log(self, level: str, message: str):
        """Record a log event."""
        with self._lock:
            entry = {
                "timestamp": datetime.utcnow().isoformat(timespec="seconds"),
                "level": level.upper(),
                "message": message,
            }
            self._events.append(entry)
            print(f"[GuardianV7] {entry['timestamp']} | {entry['level']} | {entry['message']}")

    def get_recent_events(self, limit: int = 10):
        return self._events[-limit:]

    def info(self, message: str):
        self.log("INFO", message)

    def warning(self, message: str):
        self.log("WARN", message)

    def error(self, message: str):
        self.log("ERROR", message)


# ✅ Fully disable automatic instantiation
# guardian_log = GuardianV7()  # disabled for import safety


# ============================================================
# === ASTRA GUARDIAN — Rate & Quota Monitor (v1) =============
# ============================================================
_api_counters = {}

def rate_safe(api_name, interval=60, daily_limit=None):
    """Prevent overuse of the same API globally."""
    now = time.time()
    rec = _api_counters.get(api_name, {"ts": 0, "count": 0})

    if now - rec["ts"] < interval:
        print(f"[RateSafe] {api_name} cooldown active ({interval}s).")
        return False

    if daily_limit and rec["count"] >= daily_limit:
        print(f"[RateSafe] {api_name} daily limit reached ({daily_limit}).")
        return False

    _api_counters[api_name] = {"ts": now, "count": rec["count"] + 1}
    return True


def api_usage_report():
    """Print a summary of API usage counts."""
    print("[Guardian] API Usage Summary:")
    for api, rec in _api_counters.items():
        print(f"  {api}: {rec['count']} calls today.")


# =========================================================
#  Astra Guardian — Secure API-based Live Data Access
# =========================================================
class GuardianSecureAPI:
    def __init__(self, keyfile="astra_modules/guardian/security/api_keys.json"):
        with open(keyfile, "r") as f:
            self.keys = json.load(f)
        self.timeout = 10

    def fetch_stock(self, symbol="SPY"):
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

    def fetch_crypto(self, symbol="BTC-USD"):
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
