from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _band(value: float) -> str:
    if value >= 85: return "elite"
    if value >= 70: return "strong"
    if value >= 55: return "moderate"
    return "weak"


class MemoryRetentionEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2500) + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2500) + _stable_rows(self.state_dir)
        segments: dict[str, dict[str, Any]] = defaultdict(lambda: {"sample_size": 0, "score_sum": 0.0})
        for row in rows:
            regime = str(row.get("market_regime") or row.get("regime") or "unknown").lower()
            setup = str(row.get("setup_type") or row.get("detected_setup_type") or "unknown").lower()
            cap = str(row.get("market_cap_bucket") or row.get("cap_bucket") or "unknown").lower()
            horizon = str(row.get("best_horizon_label") or row.get("recommended_hold_style") or "unknown").lower()
            grade = str(row.get("opportunity_grade") or row.get("grade") or "unknown").lower()
            entry_band = _band(_to_float(row.get("entry_quality_v3_score"), _to_float(row.get("entry_quality_score"), 0.0)))
            exit_band = _band(_to_float(row.get("exit_quality_score"), _to_float(row.get("exit_score"), 0.0)))
            key = f"{regime}|{setup}|{cap}|{horizon}|{grade}|entry_{entry_band}|exit_{exit_band}"
            outcome = _to_float(row.get("realized_return_pct"), _to_float(row.get("pnl_pct"), _to_float(row.get("opportunity_score_pct"), 50.0)))
            segments[key]["sample_size"] += 1
            segments[key]["score_sum"] += outcome
        segment_rows = []
        for key, value in segments.items():
            sample = int(value["sample_size"])
            avg = value["score_sum"] / max(1, sample)
            segment_rows.append({"memory_segment_key": key, "sample_size": sample, "average_signal": round(avg, 3)})
        segment_rows.sort(key=lambda r: (r["sample_size"], r["average_signal"]), reverse=True)
        strongest = sorted(segment_rows, key=lambda r: r["average_signal"], reverse=True)[:5]
        weakest = sorted(segment_rows, key=lambda r: r["average_signal"])[:5]
        quality = min(100.0, 30.0 + len(segment_rows) * 1.8 + min(len(rows), 200) * 0.08)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_first",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "memory_retention_status_v1": True,
            "memory_segments": segment_rows[:12],
            "memory_segment_count": len(segment_rows),
            "strongest_patterns": strongest,
            "weakest_patterns": weakest,
            "retained_lessons": ["retain regime/setup/horizon context", "separate entry quality from exit quality", "retest high-score failures first"],
            "stale_memory_segments": [r for r in segment_rows if r["sample_size"] < 2][:5],
            "memory_quality_score": round(quality, 3),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(84.0, 20.0 + len(rows) * 0.07), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "use_memory_segments_for_shadow_explanations_and_review",
        }
