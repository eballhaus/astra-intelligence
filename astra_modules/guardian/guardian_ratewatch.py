"""
guardian_ratewatch | Astra Intelligence API Usage Tracker
---------------------------------------------------------
Tracks API call usage per provider and enforces safety backoff
to prevent rate-limit lockouts. Integrated with Guardian logs.
"""

import json
import os
import time
from datetime import datetime

# Where usage data is stored
STATE_FILE = os.path.expanduser("~/astra_guardian_runtime/api_usage_log.json")

# Approximate daily API call limits per provider
LIMITS = {
    "AlphaVantage": 500,  # 25 requests/minute
    "TwelveData": 800,
    "Finnhub": 10000,
    "EODHD": 2000,
    "Moralis": 2000,
    "Polygon": 5000,
    "DataJockey": 5000,
    "SimFin": 5000,
    "Nasdaq": 1000,
}

_state = {}


def _load_state():
    """Load the existing API usage record."""
    global _state
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                _state = json.load(f)
        except Exception:
            _state = {}
    else:
        _state = {}


def _save_state():
    """Persist the current usage record."""
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(_state, f, indent=2)


def ping(api: str):
    """Register a call to API; apply sleep if near limit."""
    _load_state()
    today = datetime.utcnow().strftime("%Y-%m-%d")

    if api not in _state:
        _state[api] = {"date": today, "count": 0}
    elif _state[api].get("date") != today:
        # Reset each new day
        _state[api] = {"date": today, "count": 0}

    _state[api]["count"] += 1
    count = _state[api]["count"]
    limit = LIMITS.get(api, 10000)
    ratio = count / limit

    # Log to console (Guardian will log this automatically)
    print(f"[RateWatch] {api}: {count}/{limit} ({ratio:.1%})")

    if ratio > 1.0:
        print(f"[RateWatch] 🚫 {api} limit reached — sleeping 60s")
        time.sleep(60)
    elif ratio > 0.9:
        print(f"[RateWatch] ⚠️ Nearing {api} limit — pausing briefly")
        time.sleep(3)

    _save_state()
