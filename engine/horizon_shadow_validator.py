from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class HorizonShadowValidator:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, meta: dict[str, Any] | None = None, horizon: dict[str, Any] | None = None, intraday: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2500) + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2500)
        baseline = 50.0
        if rows:
            vals = [_to_float(r.get("opportunity_score_pct"), _to_float(r.get("confidence"), 50.0)) for r in rows]
            baseline = sum(vals) / max(1, len(vals))
        horizon_score = _to_float(((horizon or {}).get("best_horizon_summary") or {}).get("average_best_horizon_score"), baseline)
        intraday_count = _to_float(((intraday or {}).get("intraday_summary") or {}).get("day_trade_candidate_count"), 0.0)
        meta_improvement = _to_float((meta or {}).get("improvement_opportunity"), 0.0)
        horizon_adjusted = baseline * 0.75 + horizon_score * 0.25
        intraday_adjusted = horizon_adjusted + min(3.0, intraday_count * 0.35)
        meta_adjusted = intraday_adjusted + min(4.0, meta_improvement * 0.4)
        projected = max(0.0, min(12.0, meta_adjusted - baseline))
        confidence = min(85.0, 22.0 + min(len(rows), 300) * 0.12)
        recommendation = "collect_more_out_of_sample_rows" if len(rows) < 30 else "continue_shadow_validation_no_promotion"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "horizon_shadow_validation_status_v1": True,
            "baseline_opportunity_score": round(baseline, 3),
            "horizon_adjusted_score": round(horizon_adjusted, 3),
            "intraday_adjusted_score": round(intraday_adjusted, 3),
            "meta_learning_adjusted_score": round(meta_adjusted, 3),
            "projected_improvement_pct": round(projected, 3),
            "sample_size": len(rows),
            "confidence": round(confidence, 3),
            "confidence_score": round(confidence, 3),
            "recommendation": recommendation,
            "shadow_validation_summary": {
                "baseline_opportunity_score": round(baseline, 3),
                "meta_learning_adjusted_score": round(meta_adjusted, 3),
                "projected_improvement_pct": round(projected, 3),
                "recommendation": recommendation,
            },
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "do_not_promote_until_shadow_improvement_survives_walk_forward_review",
        }
