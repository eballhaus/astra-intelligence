from __future__ import annotations

from datetime import UTC, datetime


class ExecutionAnalyzer:
    def __init__(self, *args, **kwargs):
        pass

    def analyze(self) -> dict:
        return {
            "ok": True,
            "summary": {"slippage_avg": 0.0, "execution_quality": 0.0},
            "rows": [],
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

