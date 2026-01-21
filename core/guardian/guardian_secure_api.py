import json
import requests


class GuardianSecureAPI:
    from api_keys import get_available_api

    def _resolve_api(self, category="stocks"):
        """Select an available API key dynamically from API_POOLS."""
        try:
            name, key = get_available_api(category)
            print(f"[GuardianSecureAPI] ✅ Using {name} API.")
            return name, key
        except Exception as e:
            print(f"[GuardianSecureAPI] ⚠️ No valid API available: {e}")
            return None, None

    def fetch_stock(self, symbol="AAPL", limit=100):
        name, key = self._resolve_api("stocks")
        import requests, json
        if name is None:
            print("[GuardianSecureAPI] ⚠️ No valid stock API key found.")
            return {"symbol": symbol, "price": 0.0, "source": "none"}
        try:
            if name == "ALPHAVANTAGE":
                url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY_ADJUSTED&symbol={symbol}&apikey={key}"
                r = requests.get(url, timeout=10).json()
                data = list(r.get("Time Series (Daily)", {}).values())[0]
                return {"symbol": symbol, "price": float(data.get("4. close", 0.0)), "source": name}
            elif name == "TWELVEDATA":
                url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={key}"
                r = requests.get(url, timeout=10).json()
                return {"symbol": symbol, "price": float(r.get("price", 0.0)), "source": name}
            elif name == "FINNHUB":
                url = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={key}"
                r = requests.get(url, timeout=10).json()
                return {"symbol": symbol, "price": float(r.get("c", 0.0)), "source": name}
            elif name == "EODHD":
                url = f"https://eodhd.com/api/real-time/{symbol}.US?api_token={key}&fmt=json"
                r = requests.get(url, timeout=10).json()
                return {"symbol": symbol, "price": float(r.get("close", 0.0)), "source": name}
            elif name == "POLYGON":
                url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?apiKey={key}"
                r = requests.get(url, timeout=10).json()
                results = r.get("results", [{}])[0]
                return {"symbol": symbol, "price": float(results.get("c", 0.0)), "source": name}
        except Exception as e:
            print(f"[GuardianSecureAPI] ⚠️ API {name} failed for {symbol}: {e}")
            return {"symbol": symbol, "price": 0.0, "source": name}
    def __init__(self, keyfile="astra_modules/guardian/security/api_keys.json"):
        # Phase 2.4: file key loading disabled; using environment instead
        self.api_keys = {}
        return
        self.timeout = 10

    # ---------------------------------------------------------
    # Unified stock/ETF data (rotates between Alpha, Twelve, Finnhub)
    # ---------------------------------------------------------
    # ---------------------------------------------------------
    # Stock / ETF data (TwelveData → Finnhub → Polygon → EODHD)
    # ---------------------------------------------------------
    def fetch_stock(self, symbol="SPY"):
        try:
            td_key = self.keys.get("TWELVEDATA_API_KEY")
            finnhub_key = self.keys.get("FINNHUB_API_KEY")
            poly_key = self.keys.get("POLYGON_API_KEY")
            eod_key = self.keys.get("EODHD_API_KEY")

            # 1️⃣ Try TwelveData
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1min&apikey={td_key}"
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200 and "values" in r.json():
                print(f"[GuardianV7] ✅ TwelveData stock data for {symbol}")
                return r.json()

            # 2️⃣ Try Finnhub
            if finnhub_key:
                url_fh = f"https://finnhub.io/api/v1/quote?symbol={symbol}&token={finnhub_key}"
                r2 = requests.get(url_fh, timeout=self.timeout)
                if r2.status_code == 200 and "c" in r2.json():
                    print(f"[GuardianV7] ✅ Finnhub quote for {symbol}")
                    return r2.json()

            # 3️⃣ Try Polygon
            if poly_key:
                url_poly = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/prev?apiKey={poly_key}"
                r3 = requests.get(url_poly, timeout=self.timeout)
                if r3.status_code == 200:
                    print(f"[GuardianV7] ✅ Polygon stock data for {symbol}")
                    return r3.json()

            # 4️⃣ Try EODHD (end of day fallback)
            if eod_key:
                url_eod = f"https://eodhd.com/api/real-time/{symbol}.US?api_token={eod_key}&fmt=json"
                r4 = requests.get(url_eod, timeout=self.timeout)
                if r4.status_code == 200:
                    print(f"[GuardianV7] ✅ EODHD real-time data for {symbol}")
                    return r4.json()

            print(f"[GuardianV7] ⚠️ No stock data available for {symbol}")
        except Exception as e:
            print(f"[GuardianV7] ⚠️ Stock data error for {symbol}: {e}")
        return None

    def fetch_crypto(self, symbol="BTC-USD"):
        try:
            td_key = self.keys.get("TWELVEDATA_API_KEY")
            poly_key = self.keys.get("POLYGON_API_KEY")
            coin, currency = symbol.split("-")

            # Try TwelveData first
            url = f"https://api.twelvedata.com/price?symbol={coin}/{currency}&apikey={td_key}"
            r = requests.get(url, timeout=self.timeout)
            if r.status_code == 200 and "price" in r.json():
                print(f"[GuardianV7] ✅ TwelveData crypto price for {symbol}")
                return r.json()

            # Fallback: Polygon.io
            if poly_key:
                url_poly = f"https://api.polygon.io/v2/aggs/ticker/X:{coin}{currency}/prev?apiKey={poly_key}"
                r2 = requests.get(url_poly, timeout=self.timeout)
                if r2.status_code == 200:
                    print(f"[GuardianV7] ✅ Polygon crypto price for {symbol}")
                    return r2.json()

            print(f"[GuardianV7] ⚠️ No crypto data available for {symbol}")
        except Exception as e:
            print(f"[GuardianV7] ⚠️ Crypto data error for {symbol}: {e}")
        return None
