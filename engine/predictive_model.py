from __future__ import annotations

from datetime import UTC, datetime


class PredictiveModel:
    def __init__(self, *args, **kwargs):
        self._status = {"model_loaded": False, "version": "compatibility_stub"}

    def annotate_rows(self, rows):
        out = []
        for row in list(rows or []):
            r = dict(row)
            r.setdefault("predicted_win_probability", r.get("predicted_win_probability", 0.5))
            out.append(r)
        return out

    def status(self) -> dict:
        payload = dict(self._status)
        payload["last_updated_utc"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        return payload

