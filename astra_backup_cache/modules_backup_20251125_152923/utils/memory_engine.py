"""
Astra Intelligence — Rolling Learning Memory Engine (90-Day Window)
Stores scan results, rankings, forecasts, and summaries in a rotating
JSON memory file. Automatically prunes entries older than 90 days
and condenses repeated patterns to improve Astra’s internal learning.

Works with:
- Smart Scan
- Hybrid Scan
- Ranking Engine
- Forecast Engine
- Summaries
"""

import json
import os
import time
from datetime import datetime, timedelta

MEMORY_PATH = "astra_memory.json"
MAX_DAYS = 90   # rolling window


class MemoryEngine:

    def __init__(self, path: str = MEMORY_PATH):
        self.path = path
        self.data = self._load()

    # ----------------------------------------------------------
    # LOAD / SAVE
    # ----------------------------------------------------------
    def _load(self):
        if not os.path.exists(self.path):
            return {"entries": []}
        try:
            with open(self.path, "r") as f:
                return json.load(f)
        except Exception:
            return {"entries": []}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.data, f, indent=2)

    # ----------------------------------------------------------
    # PRUNE OLD ENTRIES
    # ----------------------------------------------------------
    def prune(self):
        cutoff = time.time() - (MAX_DAYS * 86400)
        self.data["entries"] = [
            e for e in self.data["entries"] if e["timestamp"] >= cutoff
        ]
        self._save()

    # ----------------------------------------------------------
    # ADD NEW LEARNING EVENT
    # ----------------------------------------------------------
    def add_event(self, symbol, event_type, payload):
        """
        event_type examples:
            - 'scan'
            - 'forecast'
            - 'ranking'
            - 'summary'
        payload = dictionary of relevant data
        """
        entry = {
            "symbol": symbol,
            "event_type": event_type,
            "payload": payload,
            "timestamp": time.time(),
        }

        self.data["entries"].append(entry)
        self.prune()
        self._save()

    # ----------------------------------------------------------
    # GET SYMBOL HISTORY (FOR LEARNING)
    # ----------------------------------------------------------
    def get_history(self, symbol):
        return [
            e for e in self.data["entries"]
            if e["symbol"].upper() == symbol.upper()
        ]

    # ----------------------------------------------------------
    # PATTERN CONDENSATION
    # Reduces noise + enhances learning
    # ----------------------------------------------------------
    def summarize_symbol(self, symbol):
        hist = self.get_history(symbol)
        if not hist:
            return None

        scans = []
        ranks = []
        forecasts = []
        summaries = []

        for e in hist:
            t = e["event_type"]
            p = e["payload"]
            if t == "scan":
                scans.append(p)
            elif t == "ranking":
                ranks.append(p)
            elif t == "forecast":
                forecasts.append(p)
            elif t == "summary":
                summaries.append(p)

        return {
            "symbol": symbol,
            "scan_count": len(scans),
            "avg_buy_score": sum([s.get("buy_score", 0) for s in scans]) / max(1, len(scans)),
            "avg_confidence": sum([s.get("confidence", 0) for s in scans]) / max(1, len(scans)),
            "avg_ranking": sum([r.get("final_score", 0) for r in ranks]) / max(1, len(ranks)),
            "forecasts": forecasts[-3:],    # last 3 forecasts
            "summaries": summaries[-3:],    # last 3 summaries
        }


memory_engine = MemoryEngine()
