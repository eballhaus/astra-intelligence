# Astra Performance System — llama_bridge.py
"""
Astra Intelligence — Llama Bridge
---------------------------------
Safe, cached interface for Llama models.
Handles sentiment, explanation, and summarization tasks asynchronously.
"""

import os
import json
import time

CACHE_PATH = "state/llama_cache.json"


class LlamaBridge:
    def __init__(self, cache_path=CACHE_PATH):
        self.cache_path = cache_path
        self.cache = self._load_cache()

    # ---------- cache helpers ----------
    def _load_cache(self):
        if os.path.exists(self.cache_path):
            with open(self.cache_path, "r") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    pass
        return {}

    def _save_cache(self):
        os.makedirs(os.path.dirname(self.cache_path), exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self.cache, f, indent=2)

    # ---------- llama usage ----------
    def get_sentiment(self, ticker, headlines, model="llama3instruct"):
        """
        Fetch or compute sentiment for a ticker based on recent headlines.
        Cached for 1 hour to minimize API calls.
        """
        now = time.time()
        item = self.cache.get(ticker)
        if item and (now - item["timestamp"]) < 3600:
            return item["data"]

        # Placeholder: connect to your Llama model here
        sentiment_score = 0.0
        explanation = f"Mock sentiment for {ticker}: neutral."
        result = {"sentiment": sentiment_score, "summary": explanation}

        self.cache[ticker] = {"timestamp": now, "data": result}
        self._save_cache()
        return result
