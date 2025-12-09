# -*- coding: utf-8 -*-
"""
Astra Intelligence — FMP API Adapter (v2.1)
-------------------------------------------
Fetches historical price data using the Financial Modeling Prep API.
"""

import pandas as pd
import requests

from astra_core.api_keys import FMP_API_KEY
from astra_core.guardian.guardian_v6 import guardian_log


def get_data(symbol: str) -> pd.DataFrame:
    guardian_log(f"[FMP] 🔄 Fetching data for {symbol}")
    try:
        url = f"https://financialmodelingprep.com/api/v3/historical-price-full/{symbol}?apikey={FMP_API_KEY}&serietype=line"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("historical", [])

        if not data:
            raise ValueError("Empty response from FMP")

        df = pd.DataFrame(data)
        df.rename(
            columns={
                "date": "date",
                "open": "open",
                "high": "high",
                "low": "low",
                "close": "close",
                "volume": "volume",
            },
            inplace=True,
        )
        df["source"] = "FMP"
        guardian_log(f"[FMP] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian_log(f"[FMP] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
