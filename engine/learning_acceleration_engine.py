from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_json, _read_jsonl, _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _symbol(row: dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "UNKNOWN").upper()


def _priority_reason(row: dict[str, Any]) -> tuple[float, str]:
    score = 35.0
    reasons: list[str] = []
    realized = _to_float(row.get("realized_return_pct"), _to_float(row.get("return_pct"), _to_float(row.get("pnl_pct"), 0.0)))
    confidence = _to_float(row.get("confidence"), 0.0)
    opportunity = _to_float(row.get("opportunity_score_pct"), _to_float(row.get("astra_composite_score"), 0.0))
    if bool(row.get("missed_profit_flag")):
        score += 24.0; reasons.append("missed_profit")
    if bool(row.get("premature_exit_flag")):
        score += 20.0; reasons.append("premature_exit")
    if bool(row.get("late_exit_flag")):
        score += 16.0; reasons.append("late_exit")
    if confidence >= 70.0 and realized < 0.0:
        score += 18.0; reasons.append("false_confidence_loss")
    if opportunity >= 70.0 and realized < 0.0:
        score += 16.0; reasons.append("high_score_failure")
    if opportunity < 55.0 and realized > 2.0:
        score += 12.0; reasons.append("low_score_winner")
    if _to_float(row.get("target_accuracy_score"), 100.0) < 45.0:
        score += 10.0; reasons.append("target_miss")
    if not reasons:
        reasons.append("representative_learning_example")
    return max(0.0, min(100.0, score)), ", ".join(reasons)


class LearningAccelerationEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        lifecycle = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2500)
        labels = _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2500)
        ledger = _read_json(f"{self.state_dir}/learning_ledger_state.json")
        stable = _stable_rows(self.state_dir)
        rows = lifecycle + labels + stable
        scored = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            score, reason = _priority_reason(row)
            scored.append({"symbol": _symbol(row), "priority_score": round(score, 3), "learning_reason": reason})
        scored.sort(key=lambda r: r["priority_score"], reverse=True)
        prioritized_count = len([r for r in scored if r["priority_score"] >= 60.0])
        eligible = int(_to_float(ledger.get("eligible_learning_rows"), len(rows)))
        current_per_day = max(1.0, min(250.0, (len(labels) + len(lifecycle)) / 7.0 if rows else 0.0))
        acceleration_factor = 1.0 + min(2.5, prioritized_count / 30.0)
        accelerated = current_per_day * acceleration_factor
        score = min(100.0, 35.0 + prioritized_count * 2.0 + len(stable) * 2.0)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_learning",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "learning_acceleration_status_v1": True,
            "learning_acceleration_score": round(score, 3),
            "prioritized_examples_count": prioritized_count,
            "eligible_learning_rows": eligible,
            "estimated_current_learning_events_per_day": round(current_per_day, 3),
            "estimated_accelerated_learning_events_per_day": round(accelerated, 3),
            "acceleration_factor": round(acceleration_factor, 3),
            "top_learning_priorities": scored[:8],
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(86.0, 28.0 + len(rows) * 0.04 + len(stable) * 4.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "review_high_priority_shadow_examples_before_policy_promotion",
        }
