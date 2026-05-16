from __future__ import annotations

import json
import os
import statistics
from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


class ExitIntelligenceEngine:
    """Advanced exit diagnostics using local lifecycle/replay state only."""

    def __init__(self, state_dir: str = "state", *args, **kwargs):
        self.state_dir = str(state_dir or "state")
        self.lifecycle_path = os.path.join(self.state_dir, "trade_lifecycle_v1.jsonl")
        self.outcome_path = os.path.join(self.state_dir, "outcome_labels_v1.jsonl")

    def evaluate_open_trades(self, open_trades, live_perf=None) -> dict:
        rows = list(open_trades or [])
        return {
            "ok": True,
            "count": len(rows),
            "alerts": [],
            "live_performance": live_perf or {},
            "last_updated_utc": _now_iso(),
        }

    def _tail_jsonl(self, path: str, limit: int = 5000) -> list[dict[str, Any]]:
        if not os.path.exists(path):
            return []
        rows: list[dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for raw in fh:
                    try:
                        obj = json.loads(raw)
                    except Exception:
                        continue
                    if isinstance(obj, dict):
                        rows.append(obj)
        except Exception:
            return []
        return rows[-max(1, int(limit)):]

    def status(self) -> dict[str, Any]:
        rows = self._tail_jsonl(self.lifecycle_path) + self._tail_jsonl(self.outcome_path)
        closed = [r for r in rows if r.get("exit_timestamp") or str(r.get("lifecycle_stage") or "").lower().startswith("closed") or r.get("pnl_pct") is not None or r.get("return_pct") is not None]
        capture = []
        missed_profit = 0
        premature = 0
        late = 0
        for row in closed:
            pnl = _to_float(row.get("pnl_pct"), _to_float(row.get("return_pct"), 0.0))
            mfe = _to_float(row.get("max_favorable_excursion_pct"), _to_float(row.get("mfe_pct"), pnl))
            mae = _to_float(row.get("max_adverse_excursion_pct"), _to_float(row.get("mae_pct"), 0.0))
            if mfe > 0.01:
                ratio = max(0.0, min(2.0, pnl / max(0.01, mfe)))
                capture.append(ratio)
                if ratio < 0.35:
                    missed_profit += 1
                if pnl > 0 and ratio < 0.45:
                    premature += 1
            if pnl < 0 and abs(mae) > 2.0:
                late += 1
        avg_capture = statistics.fmean(capture) if capture else 0.0
        sample = len(closed)
        exit_quality = min(100.0, max(0.0, avg_capture * 100.0 - (late / max(1, sample)) * 15.0))
        best_policy = "collect_more_closed_trades"
        if sample >= 30:
            best_policy = "patient_hold_with_trailing_profit_capture" if avg_capture < 0.65 else "maintain_current_exit_policy"
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_exit_intelligence_reporting_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "exit_intelligence_status_v1": True,
            "changes_live_exits": False,
            "sample_count": sample,
            "exit_quality_score": round(exit_quality, 3),
            "premature_exit_rate": round((premature / max(1, sample)) * 100.0, 3),
            "late_exit_rate": round((late / max(1, sample)) * 100.0, 3),
            "missed_profit_rate": round((missed_profit / max(1, sample)) * 100.0, 3),
            "capture_ratio": round(avg_capture, 6),
            "best_exit_policy": best_policy,
            "policy_dimensions": ["setup", "regime", "persona", "volatility_context"],
            "confidence_score": round(min(95.0, 25.0 + sample * 1.5), 3),
            "next_recommended_action": "use_exit_metrics_for_shadow_review_only_until_sample_size_is_larger",
        }
