from __future__ import annotations

from datetime import UTC, datetime


class LiveSignalLog:
    def __init__(self, *args, **kwargs):
        self._processed = 0

    def process_rankings(self, rows):
        rows = list(rows or [])
        self._processed += len(rows)
        return rows

    def live_performance(self) -> dict:
        return {
            "processed_rows": int(self._processed),
            "win_rate": 0.0,
            "avg_return": 0.0,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

