# -*- coding: utf-8 -*-
"""
Astra Intelligence — Data Orchestrator (Guardian v7 Integrated)
---------------------------------------------------------------
Bridges AstraAPI (multi-API client) with dashboard and agents.
"""

from core.api_client import AstraAPI
from core.guardian.guardian_v7 import guardian
import pandas as pd
from datetime import datetime
import time


class DataOrchestrator:
    """Unified interface for live Astra data with Guardian audit logging."""

    def __init__(self):
        self.api = AstraAPI()

    def get_live_market_data(self, symbols=None):
        if symbols is None:
            symbols = ["BTC/USD", "AAPL", "SPY"]

        frames = []
        guardian.log(
            f"[DataOrchestrator] 🧠 Initiating live data pull for {len(symbols)} symbols."
        )

        for sym in symbols:
            start_time = time.time()
            try:
                df = self.api.get_data(sym)
                latency = round(time.time() - start_time, 3)

                if df is not None and not df.empty:
                    df["symbol"] = sym
                    df["latency_s"] = latency
                    frames.append(df)
                    guardian.log(
                        f"[DataOrchestrator] ✅ {sym} fetched successfully "
                        f"(rows={len(df)}, latency={latency}s)"
                    )
                else:
                    guardian.warn(
                        f"[DataOrchestrator] ⚠️ Empty DataFrame returned for {sym}"
                    )
            except Exception as e:
                guardian.error(f"[DataOrchestrator] ❌ Failed to fetch {sym}: {e}")

        if not frames:
            guardian.error("[DataOrchestrator] ❌ No data frames returned from any API.")
            return pd.DataFrame(
                columns=["symbol", "price", "change", "timestamp", "latency_s"]
            )

        combined = pd.concat(frames, ignore_index=True)
        combined["timestamp"] = datetime.utcnow()

        if "close" in combined.columns:
            combined["price"] = combined["close"]

        if "open" in combined.columns and "close" in combined.columns:
            try:
                combined["change"] = (
                    (combined["close"] - combined["open"]) / combined["open"]
                ) * 100
            except Exception as e:
                guardian.warn(f"[DataOrchestrator] ⚠️ Change% issue: {e}")
                combined["change"] = 0.0
        else:
            combined["change"] = 0.0

        for col in ["price", "change"]:
            if col in combined.columns:
                combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0)

        guardian.log(
            f"[DataOrchestrator] 🧩 Aggregation complete — {len(combined)} rows, "
            f"{combined['symbol'].nunique()} symbols."
        )
        return combined[["symbol", "price", "change", "timestamp", "latency_s"]]
