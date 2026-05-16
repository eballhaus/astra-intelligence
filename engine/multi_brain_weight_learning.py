"""Multi-Brain Weight Learning V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except Exception: return d
class MultiBrainWeightLearning:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = state_dir
    def status(self, consensus_replay: dict[str, Any] | None = None) -> dict[str, Any]:
        c = dict(consensus_replay or {}); recs = list(c.get("adaptive_brain_weight_recommendations") or [])
        best = c.get("best_brain_accuracy") or {}; weak = c.get("weakest_brain_accuracy") or {}
        processed = int(_f(c.get("consensus_replays_processed"), 0))
        contexts = ["momentum_breakout/risk_on/technology/high_volatility", "mean_reversion/range/large_cap/low_volatility", "earnings_reaction/event_driven/mid_cap/high_volatility"]
        return {"enabled": True, "version": VERSION, "mode": "shadow_multi_brain_weight_learning_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "multi_brain_weight_learning_status_v1": True, "brain_weight_recommendations": recs[:8] or [{"brain": "Risk Brain", "recommended_weight": "monitor", "basis": "insufficient_replay_sample"}], "best_brains_by_context": [{"context": ctx, "best_brain": best.get("brain", "Risk Brain"), "basis": "shadow_replay_accuracy_proxy"} for ctx in contexts], "weakest_brains_by_context": [{"context": ctx, "weakest_brain": weak.get("brain", "Psychology Brain"), "basis": "needs_more_labeled_examples"} for ctx in contexts], "weighting_confidence": round(min(90.0, 35.0 + processed / 8.0), 3), "shadow_only": True, "live_trading_changed": False, "next_recommended_action": "collect_more_labeled_outcomes_before_weight_activation", "generated_at": _now()}
