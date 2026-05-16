"""Entry Quality Engine V3."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION = "3.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except Exception: return d
def score_entry_quality_v3(row: dict[str, Any] | None) -> dict[str, Any]:
    r = dict(row or {})
    confirmation = max(0.0, min(100.0, _f(r.get("confirmation_strength_score"), _f(r.get("agreement_score"), 50))))
    brain_agree = max(0.0, min(100.0, _f(r.get("brain_agreement_score"), 50)))
    regime = max(0.0, min(100.0, _f(r.get("regime_score"), _f(r.get("macro_adaptation_score"), 50))))
    stop = max(0.0, _f(r.get("stop_loss"), 0)); price = max(0.0, _f(r.get("price"), _f(r.get("current_price"), 0)))
    distance_from_stop = 50.0 if price <= 0 or stop <= 0 else max(0.0, min(100.0, ((price - stop) / max(price, 1.0)) * 500.0))
    volatility = max(0.0, min(100.0, _f(r.get("volatility_score"), 50)))
    momentum = max(0.0, min(100.0, _f(r.get("momentum_score"), _f(r.get("grade_percent"), 50))))
    false_breakout = max(0.0, min(100.0, 100.0 - ((confirmation * 0.35) + (brain_agree * 0.25) + (momentum * 0.25) + (regime * 0.15))))
    immediate_failure = max(0.0, min(100.0, (false_breakout * 0.45) + max(0.0, 60.0 - distance_from_stop) * 0.35 + max(0.0, volatility - 55.0) * 0.20))
    reward_risk = max(0.0, min(100.0, _f(r.get("reward_risk_quality"), 100.0 - immediate_failure)))
    entry_timing = max(0.0, min(100.0, (confirmation * 0.28) + (momentum * 0.22) + (brain_agree * 0.20) + (regime * 0.16) + (reward_risk * 0.14)))
    score = max(0.0, min(100.0, (entry_timing * 0.35) + (confirmation * 0.20) + (brain_agree * 0.15) + (regime * 0.12) + (reward_risk * 0.13) - (false_breakout * 0.05)))
    if score >= 78 and false_breakout < 35 and immediate_failure < 35: mode = "immediate"
    elif score >= 60 and immediate_failure < 55: mode = "wait_for_confirmation"
    elif score >= 45: mode = "paper_only"
    else: mode = "avoid"
    return {"entry_quality_v3_score": round(score, 3), "entry_timing_score": round(entry_timing, 3), "false_breakout_risk": round(false_breakout, 3), "confirmation_quality": round(confirmation, 3), "immediate_failure_risk": round(immediate_failure, 3), "distance_from_stop_score": round(distance_from_stop, 3), "reward_risk_quality": round(reward_risk, 3), "multi_brain_agreement": round(brain_agree, 3), "market_regime_alignment": round(regime, 3), "recommended_entry_mode": mode, "shadow_only": True}
class EntryQualityEngineV3:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = state_dir
    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [score_entry_quality_v3(r) for r in list(rows or [])[:200] if isinstance(r, dict)]
        avg = round(sum(_f(x.get("entry_quality_v3_score"), 0) for x in scored) / max(1, len(scored)), 3)
        modes = {}
        for s in scored: modes[s["recommended_entry_mode"]] = modes.get(s["recommended_entry_mode"], 0) + 1
        return {"enabled": True, "version": VERSION, "mode": "shadow_entry_quality_v3_reporting_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "entry_quality_engine_v3_status_v1": True, "entry_quality_v3_score": avg, "rows_scored_shadow": len(scored), "recommended_entry_mode_distribution": modes, "sample": scored[:6], "confidence_score": min(90, 45 + len(scored) / 8), "live_trading_changed": False, "next_recommended_action": "compare_v3_shadow_scores_against_future_outcomes_before_gate_use", "generated_at": _now()}
