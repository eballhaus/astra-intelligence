from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PositionSizingOptimizer:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def _row_score(self, row: dict[str, Any]) -> float:
        opportunity = _to_float(row.get("opportunity_score_pct"), _to_float(row.get("astra_score"), 50.0))
        confidence = _to_float(row.get("confidence"), 50.0)
        expected_return = max(0.0, min(30.0, _to_float(row.get("expected_return_pct"), 0.0))) * 100.0 / 30.0
        entry = _to_float(row.get("entry_quality_v3_score"), _to_float(row.get("entry_quality_score"), 50.0))
        psychology = 100.0 - max(0.0, min(100.0, _to_float(row.get("chase_risk"), _to_float(row.get("psychology_risk"), 40.0))))
        return max(0.0, min(100.0, opportunity * 0.35 + confidence * 0.25 + expected_return * 0.15 + entry * 0.15 + psychology * 0.10))

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _stable_rows(self.state_dir)
        scores = [self._row_score(r) for r in rows]
        avg = statistics.fmean(scores) if scores else 0.0
        if avg >= 82:
            suggested, tier = 6.0, "high_conviction_shadow"
        elif avg >= 68:
            suggested, tier = 4.0, "standard_shadow"
        elif avg >= 50:
            suggested, tier = 2.0, "starter_or_paper_shadow"
        else:
            suggested, tier = 1.0, "minimal_shadow"
        recommendations = []
        for row, score in zip(rows[:6], scores[:6]):
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            size = max(0.5, min(7.0, suggested * (score / max(1.0, avg or score or 50.0))))
            recommendations.append({
                "symbol": symbol,
                "shadow_score": round(score, 3),
                "suggested_position_size_pct": round(size, 3),
                "risk_tier": "high" if score >= 82 else "normal" if score >= 68 else "small",
            })
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "position_sizing_optimizer_status_v1": True,
            "suggested_position_size_pct": round(suggested, 3),
            "risk_tier": tier,
            "sizing_confidence": round(min(82.0, 25.0 + len(rows) * 7.5 + avg * 0.15), 3),
            "confidence_score": round(min(82.0, 25.0 + len(rows) * 7.5 + avg * 0.15), 3),
            "sizing_reason": "shadow sizing uses opportunity score, confidence, expected return, entry quality, and psychology risk from stable snapshots",
            "symbol_recommendations": recommendations,
            "sample_size": len(rows),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "manual_review_only_no_order_sizing_changes_applied",
        }
