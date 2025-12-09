# -*- coding: utf-8 -*-
"""
Astra Intelligence — TwelveData API Adapter (v2.1)
--------------------------------------------------
Fetches time series data using the TwelveData API.
"""

import pandas as pd
import requests

from astra_modules.api_keys import TWELVEDATA_API_KEY
from astra_modules.guardian.guardian_v6 import guardian_log


def get_data(symbol: str) -> pd.DataFrame:
    guardian_log(f"[TwelveData] 🔄 Fetching data for {symbol}")
    try:
        url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval=1day&outputsize=30&apikey={TWELVEDATA_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("values", [])

        if not data:
            raise ValueError("Empty data from TwelveData")

        df = pd.DataFrame(data)
        df.rename(
            columns={
                "datetime": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
            inplace=True,
        )
        df["source"] = "TwelveData"
        guardian_log(f"[TwelveData] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian_log(f"[TwelveData] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
