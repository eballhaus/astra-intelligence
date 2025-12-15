import os, requests, pandas as pd, datetime as dt

# =====================================================
# Astra Intelligence — FetchCore v7.8 (Full 6-Source Live)
# =====================================================

def fetch_unified(symbol: str, interval: str = "1h", limit: int = 100):
    symbol = symbol.upper()
    df, used = None, []
    def ok(v): return v and str(v).strip().lower() not in ["none", "null", ""]

    # --- 1️⃣ TwelveData ---
    if ok(os.getenv("TWELVEDATA_KEY")):
        try:
            r = requests.get("https://api.twelvedata.com/time_series",
                             params={"symbol": symbol, "interval": interval, "apikey": os.getenv("TWELVEDATA_KEY")},
                             timeout=10)
            j = r.json()
            if "values" in j:
                df = pd.DataFrame(j["values"])
                df.columns = [c.lower() for c in df.columns]
                df["datetime"] = pd.to_datetime(df["datetime"])
                df["symbol"] = symbol
                used.append("TwelveData")
        except Exception as e:
            print(f"[FetchCore] ⚠️ TwelveData: {e}")

    # --- 2️⃣ FMP Realtime Quote ---
    if df is None and ok(os.getenv("FMP_KEY")):
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={os.getenv('FMP_KEY')}"
            r = requests.get(url, timeout=10)
            j = r.json()
            if isinstance(j, list) and len(j) > 0:
                q = j[0]
                df = pd.DataFrame([{
                    "datetime": dt.datetime.now(),
                    "open": q.get("open"), "high": q.get("dayHigh"),
                    "low": q.get("dayLow"), "close": q.get("price"),
                    "volume": q.get("volume"), "symbol": symbol
                }])
                used.append("FMP (Realtime)")
        except Exception as e:
            print(f"[FetchCore] ⚠️ FMP: {e}")

    # --- 3️⃣ Finnhub ---
    if df is None and ok(os.getenv("FINNHUB_KEY")):
        try:
            r = requests.get(f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={os.getenv('FINNHUB_KEY')}", timeout=10)
            j = r.json()
            if "c" in j:
                df = pd.DataFrame([{
                    "datetime": dt.datetime.now(),
                    "open": j.get("o"), "high": j.get("h"),
                    "low": j.get("l"), "close": j.get("c"),
                    "volume": j.get("v", 0), "symbol": symbol
                }])
                used.append("Finnhub")
        except Exception as e:
            print(f"[FetchCore] ⚠️ Finnhub: {e}")

    # --- 4️⃣ EODHD ---
    if df is None and ok(os.getenv("EODHD_KEY")):
        try:
            url = f"https://eodhd.com/api/real-time/{symbol}.US?api_token={os.getenv('EODHD_KEY')}&fmt=json"
            r = requests.get(url, timeout=10)
            j = r.json()
            if "close" in j:
                df = pd.DataFrame([{
                    "datetime": dt.datetime.fromtimestamp(j.get("timestamp", dt.datetime.now().timestamp())),
                    "open": j.get("open"), "high": j.get("high"),
                    "low": j.get("low"), "close": j.get("close"),
                    "volume": j.get("volume"), "symbol": symbol
                }])
                used.append("EODHD")
        except Exception as e:
            print(f"[FetchCore] ⚠️ EODHD: {e}")

    # --- 5️⃣ Alpha Vantage (Daily) ---
    if df is None and ok(os.getenv("ALPHAVANTAGE_KEY")):
        try:
            url = "https://www.alphavantage.co/query"
            params = {"function": "TIME_SERIES_DAILY", "symbol": symbol, "apikey": os.getenv("ALPHAVANTAGE_KEY")}
            j = requests.get(url, params=params, timeout=10).json()
            if "Time Series (Daily)" in j:
                data = j["Time Series (Daily)"]
                recs = [{
                    "datetime": pd.to_datetime(d),
                    "open": float(v["1. open"]), "high": float(v["2. high"]),
                    "low": float(v["3. low"]), "close": float(v["4. close"]),
                    "volume": float(v["5. volume"]), "symbol": symbol
                } for d, v in list(data.items())[:limit]]
                df = pd.DataFrame(recs)
                used.append("Alpha Vantage")
        except Exception as e:
            print(f"[FetchCore] ⚠️ Alpha Vantage: {e}")

    # --- 6️⃣ Moralis v2.2 (Crypto) ---
    if df is None and symbol in ["BTC", "ETH"]:
        try:
            url = "https://deep-index.moralis.io/api/v2.2/market-data/ohlcv"
            headers = {"X-API-Key": os.getenv("MORALIS_KEY", "")}
            params = {"symbol": f"{symbol.lower()}/usd", "chain": "eth", "resolution": "1h"}
            r = requests.get(url, headers=headers, params=params, timeout=10)
            j = r.json()
            if "result" in j:
                df = pd.DataFrame(j["result"])
                used.append("Moralis v2.2")
        except Exception as e:
            print(f"[FetchCore] ⚠️ Moralis: {e}")

    if df is None or df.empty:
        print("[Astra FetchCore] ❌ All sources failed.")
        return pd.DataFrame()

    print(f"[Astra FetchCore] ✅ Data fetched from {', '.join(used)} — {len(df)} rows.")
    return df

# =====================================================
# End of File
# =====================================================
