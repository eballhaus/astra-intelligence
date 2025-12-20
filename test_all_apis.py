import os
import requests
import json

apis = {
    "TwelveData": f"https://api.twelvedata.com/time_series?symbol=SPY&interval=1h&apikey={os.getenv('TWELVEDATA_KEY')}",
    "Finnhub": f"https://finnhub.io/api/v1/quote?symbol=SPY&token={os.getenv('FINNHUB_KEY')}",
    "EODHD": f"https://eodhd.com/api/eod/SPY?api_token={os.getenv('EODHD_KEY')}&fmt=json",
    "AlphaVantage": f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol=SPY&apikey={os.getenv('ALPHAVANTAGE_KEY')}",
    "FMP": f"https://financialmodelingprep.com/api/v4/historical-price-full/SPY?apikey={os.getenv('FMP_KEY')}",
    "Moralis": "https://deep-index.moralis.io/api/v2.2/market-data/ohlcv/latest?symbol=eth/usd&chain=eth&resolution=1h",
}

headers = {"X-API-Key": os.getenv("MORALIS_KEY")}
results = []

for name, url in apis.items():
    print(f"\n🔹 Testing {name}...")
    try:
        r = requests.get(url, headers=headers if name == "Moralis" else {}, timeout=10)
        if name == "FMP" and r.status_code == 403:
            print("   ↪ Falling back to free-tier v3 endpoint...")
            r = requests.get(
                "https://financialmodelingprep.com/api/v3/historical-price-full/SPY?apikey=demo"
            )
        results.append(
            {
                "name": name,
                "status": r.status_code,
                "ok": r.ok,
                "body": r.text[:200] + "..." if len(r.text) > 200 else r.text,
            }
        )
    except Exception as e:
        results.append({"name": name, "status": "error", "error": str(e)})

print("\n✅ API STATUS SUMMARY:")
for r in results:
    print(f"• {r['name']}: {r['status']} {'✅' if r.get('ok') else '❌'}")

os.makedirs("state", exist_ok=True)
with open("state/api_status.json", "w") as f:
    json.dump(results, f, indent=2)

print("\n🧠 Results saved to state/api_status.json")
