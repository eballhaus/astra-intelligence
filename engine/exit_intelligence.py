from __future__ import annotations

from datetime import UTC, datetime


class ExitIntelligenceEngine:
    def __init__(self, *args, **kwargs):
        pass

    def evaluate_open_trades(self, open_trades, live_perf=None) -> dict:
        rows = list(open_trades or [])
        return {
            "ok": True,
            "count": len(rows),
            "alerts": [],
            "live_performance": live_perf or {},
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

