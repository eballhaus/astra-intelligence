"""Promotion Gate Refinement V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except Exception: return d
class PromotionGateRefinement:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = state_dir
    def status(self, entry_quality: dict[str, Any] | None = None, replay: dict[str, Any] | None = None) -> dict[str, Any]:
        eq = dict(entry_quality or {}); rows = int(_f(eq.get("rows_scored_shadow"), 0)); avg = _f(eq.get("entry_quality_v3_score"), 0)
        modes = dict(eq.get("recommended_entry_mode_distribution") or {})
        promoted = int(modes.get("immediate", 0) + modes.get("wait_for_confirmation", 0))
        blocked = int(modes.get("avoid", 0) + modes.get("paper_only", 0))
        over = round(max(0.0, promoted / max(1, rows) * 100.0 - max(0.0, avg - 50.0)), 3) if rows else 0.0
        under = round(max(0.0, blocked / max(1, rows) * 80.0 - max(0.0, 65.0 - avg)), 3) if rows else 0.0
        adjustments = ["raise_live_ready_confirmation_when_false_breakout_risk_is_high", "route_moderate_v3_scores_to_paper_ready", "promote_only_when_multi_brain_agreement_and_regime_alignment_confirm"]
        return {"enabled": True, "version": VERSION, "mode": "shadow_promotion_gate_refinement_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "promotion_gate_refinement_status_v1": True, "promoted_shadow_count": promoted, "blocked_shadow_count": blocked, "overpromotion_risk": over, "underpromotion_risk": under, "recommended_gate_adjustments": adjustments, "confidence_score": min(88, 40 + rows / 10), "live_trading_changed": False, "next_recommended_action": "keep_gate_changes_shadow_until_outcome_labels_confirm", "generated_at": _now()}
