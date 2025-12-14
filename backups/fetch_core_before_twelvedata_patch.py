import os, requests, pandas as pd

# =====================================================
# Astra Intelligence — Live FetchCore (Multi-API)
# =====================================================

def fetch_unified(symbol: str, interval: str = "1h", limit: int = 100):
    """Fetch unified OHLCV data using live APIs (Alpha Vantage / FMP / TwelveData)."""
    apis = {
        "ALPHAVANTAGE": os.getenv("ALPHAVANTAGE_KEY"),
        "FMP": os.getenv("FMP_KEY"),
        "TWELVEDATA": os.getenv("TWELVEDATA_KEY"),
        "FINNHUB": os.getenv("FINNHUB_KEY"),
        "EODHD": os.getenv("EODHD_KEY"),
    }

    symbol = symbol.upper()
    data = None

    try:
        if apis["FMP"]:
            url = f"https://financialmodelingprep.com/api/v3/historical-chart/1hour/{symbol}?apikey={apis['FMP']}"
            r = requests.get(url, timeout=10)
            if r.ok:
                data = r.json()
        elif apis["ALPHAVANTAGE"]:
            url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval={interval}&apikey={apis['ALPHAVANTAGE']}"
            r = requests.get(url, timeout=10)
            if r.ok:
                data = r.json().get("Time Series (1min)", {})
        elif apis["TWELVEDATA"]:
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={apis['TWELVEDATA']}"
            r = requests.get(url, timeout=10)
            if r.ok:
                data = r.json().get("values", [])

        if not data:
            print("[Astra FetchCore] ⚠️ No valid data returned from any provider.")
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df = df.rename(columns=lambda c: c.lower().replace(" ", "_"))
        df["symbol"] = symbol
        return df.head(limit)

    except Exception as e:
        print(f"[Astra FetchCore] ❌ Error fetching data: {e}")
        return pd.DataFrame()

# =====================================================
# End of File
# =====================================================
