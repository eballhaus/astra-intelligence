"""Psychology Brain V1."""
from __future__ import annotations
from datetime import UTC, datetime
from typing import Any
VERSION = "1.0.0"
def _now(): return datetime.now(UTC).isoformat().replace("+00:00", "Z")
def _f(v: Any, d: float = 0.0) -> float:
    try: return float(v)
    except Exception: return d
def score_psychology(row: dict[str, Any] | None) -> dict[str, Any]:
    r = dict(row or {})
    change = abs(_f(r.get("change_percent"), _f(r.get("change_pct"), 0)))
    momentum = _f(r.get("momentum_score"), _f(r.get("grade_percent"), 50))
    volume = _f(r.get("volume_score"), 50)
    volatility = _f(r.get("volatility_score"), 50)
    crowding = max(0.0, min(100.0, momentum * 0.45 + volume * 0.25 + change * 4.0))
    exhaustion = max(0.0, min(100.0, crowding * 0.45 + volatility * 0.25 + max(0.0, momentum - 75.0) * 0.8))
    chase = max(0.0, min(100.0, change * 7.0 + max(0.0, momentum - 65.0) * 0.7 + max(0.0, volatility - 55.0) * 0.4))
    panic = max(0.0, min(100.0, change * 6.0 + max(0.0, volatility - 60.0) * 0.8))
    fear_greed = max(0.0, min(100.0, 50.0 + (momentum - 50.0) * 0.45 - (volatility - 50.0) * 0.15))
    score = max(0.0, min(100.0, 100.0 - (crowding * 0.22 + exhaustion * 0.24 + chase * 0.30 + panic * 0.14) + (fear_greed * 0.10)))
    return {"psychology_score": round(score, 3), "crowding_risk": round(crowding, 3), "exhaustion_risk": round(exhaustion, 3), "overextension_risk": round(chase, 3), "fear_greed_proxy": round(fear_greed, 3), "panic_reversal_risk": round(panic, 3), "chase_risk": round(chase, 3), "available": True}
class PsychologyBrain:
    def __init__(self, state_dir: str = "state") -> None: self.state_dir = state_dir
    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [score_psychology(r) for r in list(rows or [])[:200] if isinstance(r, dict)]
        avg = lambda k: round(sum(_f(x.get(k), 0) for x in scored) / max(1, len(scored)), 3)
        return {"enabled": True, "version": VERSION, "mode": "local_psychology_brain_shadow_only", "local_only": True, "writes_files": False, "api_calls_used": 0, "psychology_brain_status_v1": True, "available": True, "psychology_score": avg("psychology_score"), "crowding_risk": avg("crowding_risk"), "exhaustion_risk": avg("exhaustion_risk"), "chase_risk": avg("chase_risk"), "rows_scored_shadow": len(scored), "sample": scored[:6], "confidence_score": min(88, 45 + len(scored) / 8), "live_trading_changed": False, "next_recommended_action": "use_psychology_brain_as_shadow_context_until_outcomes_confirm", "generated_at": _now()}
