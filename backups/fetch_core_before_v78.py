import os
import requests
import pandas as pd

# =====================================================
# Astra Intelligence — Live FetchCore (TwelveData Primary)
# =====================================================

def fetch_unified(symbol: str, interval: str = "1h", limit: int = 100):
    """Fetch live OHLCV data for the given symbol from TwelveData."""
    api_key = os.getenv("TWELVEDATA_KEY")
    if not api_key:
        print("[Astra FetchCore] ❌ Missing TWELVEDATA_KEY in environment.")
        return pd.DataFrame()

    symbol = symbol.upper()
    url = f"https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "apikey": api_key,
        "outputsize": limit,
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        if "values" not in data or not isinstance(data["values"], list):
            print(f"[Astra FetchCore] ⚠️ Unexpected response: {data.get('message', 'No values field.')}")
            return pd.DataFrame()

        df = pd.DataFrame(data["values"])
        df.columns = [c.lower() for c in df.columns]
        df["datetime"] = pd.to_datetime(df["datetime"])
        df = df.sort_values("datetime", ascending=True).reset_index(drop=True)
        df["symbol"] = symbol
        print(f"[Astra FetchCore] ✅ Data fetched from TwelveData ({symbol}) — {len(df)} rows.")
        return df.head(limit)

    except Exception as e:
        print(f"[Astra FetchCore] ❌ Error fetching TwelveData: {e}")
        return pd.DataFrame()

# =====================================================
# End of File
# =====================================================
