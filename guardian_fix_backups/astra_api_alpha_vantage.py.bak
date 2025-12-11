# -*- coding: utf-8 -*-
"""
Astra Intelligence — AlphaVantage API Adapter (v2.1)
---------------------------------------------------
Fetches daily time series data using the AlphaVantage API key.
Provides standardized DataFrame output for Astra Core.
"""

import pandas as pd
import requests

from astra_core.api_keys import ALPHA_VANTAGE_API_KEY
from astra_core.guardian.guardian_v6 import guardian_log


def get_data(symbol: str) -> pd.DataFrame:
    guardian_log(f"[AlphaVantage] 🔄 Fetching data for {symbol}")
    try:
        url = f"https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol={symbol}&apikey={ALPHA_VANTAGE_API_KEY}&outputsize=compact"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("Time Series (Daily)", {})

        if not data:
            raise ValueError("Empty response from AlphaVantage")

        df = pd.DataFrame(
            [
                {
                    "date": k,
                    "open": float(v["1. open"]),
                    "high": float(v["2. high"]),
                    "low": float(v["3. low"]),
                    "close": float(v["4. close"]),
                    "volume": float(v["5. volume"]),
                }
                for k, v in sorted(data.items())
            ]
        )
        df["source"] = "AlphaVantage"
        guardian_log(f"[AlphaVantage] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian_log(f"[AlphaVantage] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
