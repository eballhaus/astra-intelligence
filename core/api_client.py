"""
AstraAPI Placeholder
--------------------
Temporary compatibility client so the dashboard loads.
Replace this with your real Astra API logic when ready.
"""

import datetime

class AstraAPI:
    def __init__(self):
        print("[AstraAPI] Placeholder client initialized successfully.")

    def get_data(self, symbol: str = "ASTRA"):
        """Return a sample dataset to prevent dashboard import errors."""
        return {
            "symbol": symbol,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "value": 123.45,
            "status": "ok"
        }

