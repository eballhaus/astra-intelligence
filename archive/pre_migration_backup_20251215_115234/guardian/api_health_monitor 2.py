"""
Guardian API Health Monitor — Astra v7.1
Checks API health, latency, and rotates priority order dynamically.
"""

import time, requests, json
from datetime import datetime

API_ENDPOINTS = {
    "TwelveData": "https://api.twelvedata.com/time_series?symbol=SPY&interval=1h",
    "Finnhub": "https://finnhub.io/api/v1/quote?symbol=AAPL",
    "EODHD": "https://eodhd.com/api/eod/SPY",
    "AlphaVantage": "https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=SPY",
    "FMP": "https://financialmodelingprep.com/api/v4/historical-price-full/SPY",
    "Moralis": "https://deep-index.moralis.io/api/v2.2/market-data/ohlcv",
}

def ping_api(name, url):
    start = time.time()
    try:
        r = requests.get(url, timeout=5)
        latency = round((time.time() - start) * 1000)
        status = r.status_code
        return {"name": name, "status": status, "latency_ms": latency}
    except Exception as e:
        return {"name": name, "status": "error", "error": str(e)}

def check_all():
    results = [ping_api(name, url) for name, url in API_ENDPOINTS.items()]
    path = "state/api_status.json"
    for r in results:
        r["timestamp"] = datetime.now().isoformat()
    with open(path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"[Guardian] ✅ Health check complete — results saved to {path}")
    for r in results:
        print(f"• {r['name']}: {r['status']} ({r.get('latency_ms', '?')} ms)")

if __name__ == "__main__":
    check_all()

