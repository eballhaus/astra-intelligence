import json
import requests
from api_keys import (
    ALPHAVANTAGE_API_KEY,
    TWELVEDATA_API_KEY,
    FINNHUB_API_KEY,
    EODHD_API_KEY,
    POLYGON_API_KEY,
    NASDAQ_API_KEY,
    DATAJOCKEY_API_KEY,
    SIMFIN_API_KEY,
    MORALIS_API_KEY,
)


class GuardianSecureAPI:
    def __init__(self):
        self.keys = {
            "ALPHAVANTAGE_API_KEY": ALPHAVANTAGE_API_KEY,
            "TWELVEDATA_API_KEY": TWELVEDATA_API_KEY,
            "FINNHUB_API_KEY": FINNHUB_API_KEY,
            "EODHD_API_KEY": EODHD_API_KEY,
            "POLYGON_API_KEY": POLYGON_API_KEY,
            "NASDAQ_API_KEY": NASDAQ_API_KEY,
            "DATAJOCKEY_API_KEY": DATAJOCKEY_API_KEY,
            "SIMFIN_API_KEY": SIMFIN_API_KEY,
            "MORALIS_API_KEY": MORALIS_API_KEY,
        }
        self.timeout = 10

    # -----------------------------------------------
    # Stock Data Fetch
    # -----------------------------------------------
    def fetch_stock(self, symbol="SPY"):
        """Fetch live stock/ETF data from TwelveData or Alpha Vantage."""
        td_key = self.keys.get("TWELVEDATA_API_KEY")
        try:
            if td_key:
                url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1min&apikey={td_key}"
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    j = r.json()
                    if "values" in j:
                        print(f"[GuardianSecureAPI] ✅ Live TwelveData data for {symbol}")
                        return j
        except Exception as e:
            print(f"[GuardianSecureAPI] ⚠️ TwelveData error for {symbol}: {e}")

        av_key = self.keys.get("ALPHAVANTAGE_API_KEY")
        try:
            if av_key:
                url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval=1min&apikey={av_key}"
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200 and "Time Series" in r.text:
                    print(f"[GuardianSecureAPI] ✅ Live AlphaVantage data for {symbol}")
                    return r.json()
        except Exception as e:
            print(f"[GuardianSecureAPI] ⚠️ AlphaVantage error for {symbol}: {e}")

        print(f"[GuardianSecureAPI] ❌ No live stock data available for {symbol}.")
        return None

    # -----------------------------------------------
    # Crypto Data Fetch
    # -----------------------------------------------
    def fetch_crypto(self, symbol="BTC-USD"):
        """Fetch live crypto data via Moralis or CoinMarketCap."""
        moralis_key = self.keys.get("MORALIS_API_KEY")
        try:
            if moralis_key:
                url = f"https://deep-index.moralis.io/api/v2/market-data/erc20/{symbol}"
                headers = {"X-API-Key": moralis_key}
                r = requests.get(url, headers=headers, timeout=self.timeout)
                if r.status_code == 200:
                    print(f"[GuardianSecureAPI] ✅ Live Moralis data for {symbol}")
                    return r.json()
        except Exception as e:
            print(f"[GuardianSecureAPI] ⚠️ Moralis error for {symbol}: {e}")

        print(f"[GuardianSecureAPI] ❌ No live crypto data available for {symbol}.")
        return None
