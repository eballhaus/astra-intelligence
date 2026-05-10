from __future__ import annotations

from datetime import UTC, datetime


class RegimeEngine:
    def __init__(self, *args, **kwargs):
        pass

    def annotate_rows(self, rows):
        out = []
        for row in list(rows or []):
            r = dict(row)
            r.setdefault("regime_context", "unknown")
            out.append(r)
        return out

    def market_regime_snapshot(self) -> dict:
        return {
            "ok": True,
            "regime": "unknown",
            "confidence": 0.0,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

