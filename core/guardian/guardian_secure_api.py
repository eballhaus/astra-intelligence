import json, requests, os

class GuardianSecureAPI:
    def __init__(self, keyfile="astra_modules/guardian/security/api_keys.json"):
        with open(keyfile, "r") as f:
            self.keys = json.load(f)
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
