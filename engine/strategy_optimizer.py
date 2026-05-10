from __future__ import annotations

from datetime import UTC, datetime


class StrategyOptimizer:
    def __init__(self, *args, **kwargs):
        pass

    def recommend(self) -> dict:
        return {
            "ok": True,
            "recommendations": [],
            "confidence": 0.0,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

