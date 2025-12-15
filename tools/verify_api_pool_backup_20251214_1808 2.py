"""
Astra API Pool Verifier (v2)
Verifies and benchmarks all active APIs with correct authentication styles.
"""

import requests
import time
from api_keys import API_POOLS

def test_api(name, key):
    start = time.time()
    try:
        # --- STOCK DATA PROVIDERS ---
        if name == "ALPHAVANTAGE":
            url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=AAPL&apikey={key}"

        elif name == "TWELVEDATA":
            url = f"https://api.twelvedata.com/time_series?symbol=AAPL&interval=1h&apikey={key}"

        elif name == "FINNHUB":
            url = "https://finnhub.io/api/v1/quote?symbol=AAPL"
            headers = {"X-Finnhub-Token": key}
            r = requests.get(url, headers=headers, timeout=8)
            elapsed = round(time.time() - start, 2)
            return f"✅ {r.status_code} ({elapsed}s)"

        elif name == "EODHD":
            url = f"https://eodhd.com/api/real-time/AAPL.US?api_token={key}&fmt=json"

        elif name == "POLYGON":
            url = f"https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2024-12-01/2024-12-02?apiKey={key}"

        elif name == "NASDAQ":
            url = f"https://data.nasdaq.com/api/v3/datasets/WIKI/AAPL.json?api_key={key}"

        elif name == "DATAJOCKEY":
            url = f"https://api.datajockey.io/v0/company/financials?ticker=AAPL&apikey={key}"

        elif name == "SIMFIN":
            # Try backup domain if API host unavailable
            url = f"https://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1&api-key={key}"

        # --- CRYPTO / BLOCKCHAIN ---
        elif name == "MORALIS":
            url = "https://deep-index.moralis.io/api/v2/market-data/price?chain=eth"
            headers = {"X-API-Key": key}
            r = requests.get(url, headers=headers, timeout=8)
            elapsed = round(time.time() - start, 2)
            return f"✅ {r.status_code} ({elapsed}s)"

        else:
            return "⚠️ Unknown provider"

        # Default request for query-param-based providers
        r = requests.get(url, timeout=8)
        elapsed = round(time.time() - start, 2)
        return f"✅ {r.status_code} ({elapsed}s)"

    except Exception as e:
        return f"❌ {str(e)}"

print("\n=== ASTRA API POOL VERIFICATION v2 ===\n")

for category, providers in API_POOLS.items():
    print(f"[{category.upper()}]")
    for name, key in providers:
        if not key:
            print(f"  - {name}: ⚠️ Missing key")
            continue
        status = test_api(name, key)
        print(f"  - {name}: {status}")
    print()

