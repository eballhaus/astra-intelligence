from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _stable_rows, _to_float
from engine.learning_acceleration_engine import _priority_reason

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class PrioritizedExperienceReplay:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2000) + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2000) + _stable_rows(self.state_dir)
        candidates = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            priority, reason = _priority_reason(row)
            candidates.append({
                "symbol": str(row.get("symbol") or row.get("ticker") or "UNKNOWN").upper(),
                "priority_score": round(priority, 3),
                "replay_reason": reason,
                "realized_return_pct": round(_to_float(row.get("realized_return_pct"), _to_float(row.get("pnl_pct"), 0.0)), 3),
                "opportunity_score_pct": round(_to_float(row.get("opportunity_score_pct"), 0.0), 3),
            })
        candidates.sort(key=lambda r: r["priority_score"], reverse=True)
        batch_size = min(24, max(6, len(candidates) // 4)) if candidates else 0
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_first",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "prioritized_replay_status_v1": True,
            "replay_candidates": candidates[:12],
            "replay_candidate_count": len(candidates),
            "replay_batch_size": batch_size,
            "replay_ready": batch_size > 0,
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(84.0, 25.0 + len(candidates) * 0.18), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "run_replay_batches_only_during_idle_shadow_windows",
        }
