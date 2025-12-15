# -*- coding: utf-8 -*-
"""
Astra Intelligence — Moralis API Adapter (v2.1)
-----------------------------------------------
Fetches crypto OHLC data via the Moralis Market Data API.
"""

import pandas as pd
import requests

from astra_core.api_keys import MORALIS_API_KEY
from astra_core.guardian.guardian_v6 import guardian


def get_data(symbol: str) -> pd.DataFrame:
    guardian.log(f"[Moralis] 🔄 Fetching data for {symbol}")
    try:
        headers = {"X-API-Key": MORALIS_API_KEY}
        url = f"https://deep-index.moralis.io/api/v2/market-data/ohlcv?symbol={symbol}&interval=1d&limit=30"
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json().get("data", [])

        if not data:
            raise ValueError("Empty response from Moralis")

        df = pd.DataFrame(data)
        df.rename(
            columns={
                "t": "date",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
            },
            inplace=True,
        )
        df["source"] = "Moralis"
        guardian.log(f"[Moralis] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian.log(f"[Moralis] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
