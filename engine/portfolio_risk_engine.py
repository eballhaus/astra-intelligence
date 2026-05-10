from __future__ import annotations

from datetime import UTC, datetime


class PortfolioRiskEngine:
    def __init__(self, *args, **kwargs):
        pass

    def enrich(self, rows, *args, **kwargs):
        out = []
        for row in list(rows or []):
            r = dict(row)
            r.setdefault("portfolio_risk_score", 0.0)
            out.append(r)
        return out

    def snapshot(self) -> dict:
        return {
            "ok": True,
            "portfolio_risk_score": 0.0,
            "position_count": 0,
            "last_updated_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        }

