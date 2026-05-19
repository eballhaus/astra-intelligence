from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ExitOptimizationShadow:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        lifecycle = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl")
        labels = _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl")
        rows = lifecycle + labels
        sample_size = len(rows)
        exit_scores = [_to_float(r.get("exit_quality_score"), _to_float(r.get("exit_score"), 0.0)) for r in rows if r.get("exit_quality_score") is not None or r.get("exit_score") is not None]
        premature = len([r for r in rows if bool(r.get("premature_exit_flag"))])
        late = len([r for r in rows if bool(r.get("late_exit_flag"))])
        missed = len([r for r in rows if bool(r.get("missed_profit_flag"))])
        r_mult = [_to_float(r.get("realized_R_multiple"), _to_float(r.get("r_multiple"), 0.0)) for r in rows if r.get("realized_R_multiple") is not None or r.get("r_multiple") is not None]
        avg_exit_quality = statistics.fmean(exit_scores) if exit_scores else 50.0 if sample_size else 0.0
        denom = max(1, sample_size)
        if missed > premature and missed >= late:
            policy = "shadow_test_more_patient_trailing_exit_with_target_zone_confirmation"
            reason = "missed-profit evidence is the dominant exit issue"
        elif premature > late and premature > 0:
            policy = "shadow_test_multi_cycle_confirmation_before_non_stop_exits"
            reason = "premature-exit labels exceed late-exit labels"
        elif late > 0:
            policy = "shadow_test_tighter_profit_protection_after_target_zone_rejection"
            reason = "late-exit labels suggest exits need faster deterioration confirmation"
        else:
            policy = "keep_current_exit_policy_shadow_baseline"
            reason = "insufficient labeled exit separation for a stronger recommendation"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "exit_optimization_shadow_status_v1": True,
            "average_exit_quality": round(avg_exit_quality, 3),
            "premature_exit_rate": round(premature * 100.0 / denom, 3),
            "late_exit_rate": round(late * 100.0 / denom, 3),
            "missed_profit_rate": round(missed * 100.0 / denom, 3),
            "average_realized_r_multiple": round(statistics.fmean(r_mult), 3) if r_mult else None,
            "sample_size": sample_size,
            "best_shadow_exit_policy": policy,
            "recommendation_reason": reason,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(85.0, 20.0 + sample_size * 0.2), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "evaluate_shadow_exit_policy_with_walk_forward_gate_before_any_manual_use",
        }
