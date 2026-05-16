"""Outcome Labeling Engine V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except Exception: return d
LABELS = ["good_entry", "bad_entry", "early_exit", "late_exit", "missed_profit", "clean_win", "fast_loss", "weak_follow_through", "strong_follow_through", "false_confidence", "valid_confidence"]
class OutcomeLabelingEngine:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = state_dir
    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        labels = {k: 0 for k in LABELS}; missing = 0
        for r in list(rows or [])[:1000]:
            if not isinstance(r, dict): continue
            ret = _f(r.get("return_pct"), _f(r.get("pnl_pct"), _f(r.get("profit_pct"), 0)))
            conf = _f(r.get("confidence"), _f(r.get("predicted_win_probability"), 0))
            eq = _f(r.get("entry_quality_score"), _f(r.get("entry_quality_v3_score"), 0))
            if ret > 0: labels["clean_win"] += 1
            elif ret < -1.0: labels["fast_loss"] += 1
            else: missing += 1
            if eq >= 65: labels["good_entry"] += 1
            elif eq > 0: labels["bad_entry"] += 1
            if conf >= 75 and ret < 0: labels["false_confidence"] += 1
            if conf >= 65 and ret > 0: labels["valid_confidence"] += 1
            if _f(r.get("follow_through_score"), 50) >= 60: labels["strong_follow_through"] += 1
            else: labels["weak_follow_through"] += 1
        created = sum(labels.values())
        quality = round(min(95.0, 35.0 + created / 20.0), 3)
        return {"enabled": True, "version": VERSION, "mode": "shadow_outcome_labeling_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "outcome_labeling_status_v1": True, "labels_created_shadow": created, "label_counts_shadow": labels, "labels_missing": missing, "label_confidence": quality, "label_quality_score": quality, "live_trading_changed": False, "next_recommended_action": "persist_labels_only_after_operator_approved_schema_review", "generated_at": _now()}
