# -*- coding: utf-8 -*-
"""
Astra Intelligence — Finnhub API Adapter (v2.1)
-----------------------------------------------
Fetches crypto candle data from Finnhub using the live API token.
"""

import time

import pandas as pd
import requests

from astra_core.api_keys import FINNHUB_API_KEY
from astra_core.guardian.guardian_v6 import guardian


def get_data(symbol: str) -> pd.DataFrame:
    guardian.log(f"[Finnhub] 🔄 Fetching data for {symbol}")
    try:
        now = int(time.time())
        month_ago = now - (30 * 86400)
        url = f"https://finnhub.io/api/v1/crypto/candle?symbol={symbol}&resolution=D&from={month_ago}&to={now}&token={FINNHUB_API_KEY}"
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        if not data or data.get("s") != "ok":
            raise ValueError("Invalid response from Finnhub")

        df = pd.DataFrame(
            {
                "date": pd.to_datetime(data["t"], unit="s"),
                "open": data["o"],
                "high": data["h"],
                "low": data["l"],
                "close": data["c"],
                "volume": data["v"],
            }
        )
        df["source"] = "Finnhub"
        guardian.log(f"[Finnhub] ✅ Retrieved {len(df)} rows for {symbol}")
        return df

    except Exception as e:
        guardian.log(f"[Finnhub] ⚠️ Error fetching {symbol}: {e}")
        return pd.DataFrame()
