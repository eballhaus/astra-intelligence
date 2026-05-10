from __future__ import annotations

from datetime import UTC, datetime


class PersonaPerformanceTracker:
    def __init__(self, *args, **kwargs):
        pass

    def summary(self) -> dict:
        return {
            "persona_count": 0,
            "best_persona": "unknown",
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

