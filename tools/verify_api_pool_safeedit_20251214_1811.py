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
            url = f"https://data.nasdaq.com/api/v3/datasets/WIKI/AAPL/data.json?api_key={key}"

        elif name == "DATAJOCKEY":
            url = f"https://api.datajockey.io/v0/company/financials?ticker=AAPL&apikey={key}"

        elif name == "SIMFIN":
            # Try backup domain if API host unavailable
            url = f"https://api.simfin.com/v2/companies/statements?statement=plhttps://api.simfin.com/v2/companies/statements?statement=plhttps://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1fyear=2023https://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1ticker=AAPL&api-key={key}"fyear=2023https://api.simfin.com/v2/companies/statements?statement=plhttps://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1fyear=2023https://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1ticker=AAPL&api-key={key}"ticker=AAPLhttps://api.simfin.com/v2/companies/statements?statement=plhttps://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1fyear=2023https://simfin.com/api/v3/companies/id/111052/statements?statement=pl&fyear=2023&ptype=Q1ticker=AAPL&api-key={key}"api-key=ed5d0804-84b8-45b6-b898-51db3914943b"

        # --- CRYPTO / BLOCKCHAIN ---
        elif name == "MORALIS":
            url = "https://deep-index.moralis.io/api/v3/market-data/token-price?chain=ethhttps://deep-index.moralis.io/api/v3/market-data/price?chain=ethaddress=0xC02aaa39b223FE8D0A0e5C4F27eAD9083C756Cc2"
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

