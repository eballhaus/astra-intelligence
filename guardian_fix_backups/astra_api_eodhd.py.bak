# -*- coding: utf-8 -*-
"""
Astra Intelligence — EODHD API Adapter (v2.1)
---------------------------------------------
Fetches EOD historical data using the EODHD token.
"""

import pandas as pd
import requests

from astra_core.api_keys import EODHD_API_KEY
from astra_core.guardian.guardian_v6 import guardian_log


def get_data(symbol: str) -> pd.DataFrame:
    guardian_log(f"[EODHD] 🔄 Fetching data for {symbol}")
    try:
        url = (
            f"https://eodhd.com/api/eod/{symbol}.US?api_token={EODHD_API_KEY}&fmt=json"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list):
            raise ValueError("Invalid data structure from EODHD")

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
        df["source"] = "EODHD"
        guardian_log(f"[EODHD] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian_log(f"[EODHD] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
