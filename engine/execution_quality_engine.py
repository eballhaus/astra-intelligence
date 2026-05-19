from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _avg(values: list[float], default: float = 0.0) -> float:
    return statistics.fmean(values) if values else default


class ExecutionQualityEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2500) + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2500) + _stable_rows(self.state_dir)
        entry_scores = [_to_float(r.get("entry_quality_v3_score"), _to_float(r.get("entry_quality_score"), 0.0)) for r in rows if r.get("entry_quality_v3_score") is not None or r.get("entry_quality_score") is not None]
        exit_scores = [_to_float(r.get("exit_quality_score"), _to_float(r.get("exit_score"), 0.0)) for r in rows if r.get("exit_quality_score") is not None or r.get("exit_score") is not None]
        target_scores = [_to_float(r.get("target_accuracy_score"), 0.0) for r in rows if r.get("target_accuracy_score") is not None]
        r_mult = [_to_float(r.get("realized_r_multiple"), 0.0) for r in rows if r.get("realized_r_multiple") is not None]
        trailing = [_to_float(r.get("trailing_stop_score"), _to_float(r.get("profit_protection_status_score"), 0.0)) for r in rows if r.get("trailing_stop_score") is not None or r.get("profit_protection_status_score") is not None]
        entry = _avg(entry_scores, 55.0)
        exit_q = _avg(exit_scores, 50.0)
        target = _avg(target_scores, 50.0)
        realized_r_quality = max(0.0, min(100.0, 50.0 + _avg(r_mult, 0.0) * 18.0))
        trailing_score = _avg(trailing, 50.0)
        overall = entry * 0.28 + exit_q * 0.24 + target * 0.20 + realized_r_quality * 0.16 + trailing_score * 0.12
        recs = []
        if target < 55: recs.append("tighten_target_zone_calibration_shadow")
        if exit_q < 55: recs.append("require_multi_cycle_exit_confirmation_shadow")
        if entry < 55: recs.append("prioritize_cleaner_entry_confirmation_shadow")
        if not recs: recs.append("continue_collecting_execution_quality_labels")
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_first",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "execution_quality_status_v1": True,
            "execution_quality_score": round(overall, 3),
            "entry_quality_shadow": round(entry, 3),
            "exit_quality_shadow": round(exit_q, 3),
            "target_accuracy_score": round(target, 3),
            "realized_r_quality": round(realized_r_quality, 3),
            "trailing_stop_score": round(trailing_score, 3),
            "execution_recommendations": recs,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(86.0, 24.0 + len(rows) * 0.08), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "track_execution_quality_shadow_fields_on_future_paper_outcomes",
        }
