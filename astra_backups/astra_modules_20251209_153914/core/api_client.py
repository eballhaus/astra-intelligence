# astra_modules/core/api_client.py
# ================================================================
# AstraAPI — Unified Live Market Data Client (v3.0)
# ================================================================

from datetime import datetime, timezone

import pandas as pd
import requests

from astra_modules.guardian.guardian_v6 import guardian_log

# ===================================================================
# 🔐 API KEYS (from your api_keys.py or environment variables)
# ===================================================================
ALPHA_VANTAGE_API_KEY = "YJVYAJJSKKXF3ZQB"
FMP_API_KEY = "xbgYJPXsiwJ3coLczphQSBsghO7fTklM"
TWELVEDATA_API_KEY = "452b5c89fc8747d4803ee6bda5f891b2"
FINNHUB_API_KEY = "d42ee5hr01qorleqvvb0d42ee5hr01qorleqvvbg"
EODHD_API_KEY = "6904e7a2ced028.25933984"
MORALIS_API_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJub25jZSI6IjUxNGFmZTQ0LTA5NjQtNGY0OS1iMzY0LTBhY2IzNGI1Yzc4MyIsIm9yZ0lkIjoiNDc5MDgy"
    "IiwidXNlcklkIjoiNDkyODc5IiwidHlwZUlkIjoiMGE0Yzg2YjMtNTFjMC00MzIwLWI2YzYtODU3NmY5NDhh"
    "ZWYyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjIwNTQ0NzYsImV4cCI6NDkxNzgxNDQ3Nn0."
    "qD2enThc_vEplne8qVqOxDJrCUherTPWb-jmpebvkyI"
)


# ===================================================================
# 🧠 AstraAPI Implementation
# ===================================================================


class AstraAPI:
    """Primary Astra data client — fetches live stock and crypto prices."""

    def __init__(self):
        self.session = requests.Session()

    # ---------------------------------------------------------------
    # Main unified fetch
    # ---------------------------------------------------------------
    def get_data(self, symbol: str, *args, **kwargs) -> pd.DataFrame:
        """Return live market data for a stock or crypto symbol."""
        symbol = symbol.upper().strip()
        guardian_log(f"[AstraAPI] 🔗 Fetching live data for {symbol} ...")

        try:
            if "/" in symbol:
                df = self._get_crypto(symbol)
            else:
                df = self._get_equity(symbol)

            if df is not None and not df.empty:
                guardian_log(
                    f"[AstraAPI] ✅ LIVE data fetched for {symbol} (my_api_live)"
                )
                return df

        except Exception as e:
            guardian_log(
                f"[AstraAPI] ⚠️ Live data fetch failed for {symbol}: {e}")

        # Fallback empty dataframe
        return pd.DataFrame()

    # ---------------------------------------------------------------
    # 🏦 Stocks & ETFs
    # ---------------------------------------------------------------
    def _get_equity(self, symbol: str) -> pd.DataFrame:
        """Try multiple stock data providers in order of reliability."""
        now = datetime.now(timezone.utc)

        # 1️⃣ Alpha Vantage
        try:
            url = f"https://www.alphavantage.co/query?function=TIME_SERIES_INTRADAY&symbol={symbol}&interval=5min&apikey={ALPHA_VANTAGE_API_KEY}"
            series = (
                self.session.get(url, timeout=5).json().get(
                    "Time Series (5min)", {})
            )
            data_points = list(series.items())[-50:]  # last 50 candles

            df = pd.DataFrame(
                [
                    {
                        "timestamp": pd.to_datetime(t, utc=True),
                        "open": float(vals["1. open"]),
                        "high": float(vals["2. high"]),
                        "low": float(vals["3. low"]),
                        "close": float(vals["4. close"]),
                        "volume": int(vals["5. volume"]),
                    }
                    for t, vals in data_points
                ]
            )
            price = float(data.get("05. price"))
            df = pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "open": float(data.get("02. open", price)),
                        "high": float(data.get("03. high", price)),
                        "low": float(data.get("04. low", price)),
                        "close": price,
                        "volume": int(float(data.get("06. volume", 0))),
                    }
                ]
            )
            df.attrs = {
                "source": "alpha_vantage",
                "symbol": symbol,
                "timestamp": now,
                "price": price,
                "data_fresh": True,
                "confidence": 0.98,
            }
            return df
        except Exception:
            guardian_log(f"[AstraAPI] ⚠️ Alpha Vantage failed for {symbol}")

        # 2️⃣ Financial Modeling Prep
        try:
            url = f"https://financialmodelingprep.com/api/v3/quote/{symbol}?apikey={FMP_API_KEY}"
            data = self.session.get(url, timeout=5).json()[0]
            price = float(data.get("price", 0))
            df = pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "open": float(data.get("open", price)),
                        "high": float(data.get("dayHigh", price)),
                        "low": float(data.get("dayLow", price)),
                        "close": price,
                        "volume": int(float(data.get("volume", 0))),
                    }
                ]
            )
            df.attrs = {
                "source": "fmp_api",
                "symbol": symbol,
                "timestamp": now,
                "price": price,
                "data_fresh": True,
                "confidence": 0.97,
            }
            return df
        except Exception:
            guardian_log(f"[AstraAPI] ⚠️ FMP fallback failed for {symbol}")

        # 3️⃣ Twelve Data fallback
        try:
            url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TWELVEDATA_API_KEY}"
            data = self.session.get(url, timeout=5).json()
            price = float(data.get("price", 0))
            df = pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "open": price,
                        "high": price * 1.002,
                        "low": price * 0.998,
                        "close": price,
                        "volume": 0,
                    }
                ]
            )
            df.attrs = {
                "source": "twelvedata",
                "symbol": symbol,
                "timestamp": now,
                "price": price,
                "data_fresh": True,
                "confidence": 0.95,
            }
            return df
        except Exception:
            guardian_log(
                f"[AstraAPI] ⚠️ TwelveData fallback failed for {symbol}")

        return pd.DataFrame()

    # ---------------------------------------------------------------
    # 💰 Cryptocurrencies
    # ---------------------------------------------------------------
    def _get_crypto(self, symbol: str) -> pd.DataFrame:
        """Fetch crypto market data using Moralis."""
        now = datetime.now(timezone.utc)
        base, quote = symbol.split("/")
        price = None

        # 1️⃣ Moralis
        try:
            headers = {"X-API-Key": MORALIS_API_KEY}
            url = f"https://deep-index.moralis.io/api/v2/market-data/price?symbol={base}&currency={quote}"
            data = self.session.get(url, headers=headers, timeout=5).json()
            price = float(data.get("usdPrice", 0)
                          ) if "usdPrice" in data else None
        except Exception:
            guardian_log(
                f"[AstraAPI] ⚠️ Moralis crypto fetch failed for {symbol}")

        # 2️⃣ TwelveData fallback
        if not price:
            try:
                url = f"https://api.twelvedata.com/price?symbol={base}/{quote}&apikey={TWELVEDATA_API_KEY}"
                data = self.session.get(url, timeout=5).json()
                price = float(data.get("price", 0))
            except Exception:
                guardian_log(
                    f"[AstraAPI] ⚠️ TwelveData crypto fallback failed for {symbol}"
                )

        if not price:
            return pd.DataFrame()

        df = pd.DataFrame(
            [
                {
                    "timestamp": now,
                    "open": price * 0.999,
                    "high": price * 1.001,
                    "low": price * 0.998,
                    "close": price,
                    "volume": 0,
                }
            ]
        )
        df.attrs = {
            "source": "my_api_live",
            "symbol": symbol,
            "timestamp": now,
            "price": price,
            "data_fresh": True,
            "confidence": 0.99,
        }
        return df


# ===================================================================
# 🔧 Manual Test
# ===================================================================
if __name__ == "__main__":
    api = AstraAPI()
    for sym in ["AAPL", "MSFT", "BTC/USD", "ETH/USD"]:
        df = api.get_data(sym)
        print(f"{sym}: {df.attrs.get('price')} from {df.attrs.get('source')}")
