"""Replay-to-Learning Integration V1."""
from __future__ import annotations
import json, os
from datetime import UTC, datetime
from typing import Any
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _read_jsonl(path: str, limit: int = 2000) -> list[dict[str, Any]]:
    rows = []
    if not os.path.exists(path): return rows
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                try: obj = json.loads(raw)
                except Exception: continue
                if isinstance(obj, dict): rows.append(obj)
    except Exception: return rows
    return rows[-limit:]
class ReplayToLearningIntegration:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.paths = [
            os.path.join(self.state_dir, "replay_counterfactual_v1.jsonl"),
            os.path.join(self.state_dir, "multi_brain_replay_v1.jsonl"),
            os.path.join(self.state_dir, "candidate_decision_ledger_v1.jsonl"),
            os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl"),
            os.path.join(self.state_dir, "outcome_labels_v1.jsonl"),
        ]
    def rows(self) -> list[dict[str, Any]]:
        out = []
        for p in self.paths: out.extend(_read_jsonl(p))
        return out[-2500:]
    def status(self) -> dict[str, Any]:
        rows = self.rows(); reason_counts = {}; eligible = 0
        for r in rows:
            has_symbol = bool(str(r.get("symbol") or r.get("ticker") or "").strip())
            has_outcome = any(k in r for k in ("outcome", "outcome_label", "return_pct", "pnl", "label"))
            if has_symbol and has_outcome: eligible += 1
            else:
                key = "missing_symbol" if not has_symbol else "missing_outcome_label"
                reason_counts[key] = reason_counts.get(key, 0) + 1
        integrated = min(eligible, max(0, int(len(rows) * 0.8)))
        confidence = round(min(92.0, 35.0 + integrated / 20.0 + len(reason_counts) * 2.0), 3)
        return {"enabled": True, "version": VERSION, "mode": "shadow_replay_to_learning_reporting_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "replay_to_learning_status_v1": True, "replay_rows_available": len(rows), "replay_rows_integrated_shadow": integrated, "integration_confidence": confidence, "eligible_learning_rows": eligible, "rejected_rows_reason_counts": reason_counts, "live_trading_changed": False, "next_recommended_action": "review_shadow_learning_rows_before_any_policy_activation", "generated_at": _now()}
