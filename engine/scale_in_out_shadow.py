from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class ScaleInOutShadow:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _stable_rows(self.state_dir)
        signals = []
        for row in rows[:12]:
            symbol = str(row.get("symbol") or row.get("ticker") or "UNKNOWN").upper()
            confidence = _to_float(row.get("confidence"), 0.0)
            opportunity = _to_float(row.get("opportunity_score_pct"), _to_float(row.get("astra_composite_score"), 0.0))
            conviction = _to_float(row.get("conviction_10r"), 0.0)
            exit_score = _to_float(row.get("averaged_exit_score"), _to_float(row.get("exit_score"), 50.0))
            target_progress = _to_float(row.get("target_progress_pct"), 0.0)
            scale_in = confidence >= 75 and opportunity >= 72 and conviction >= 65 and exit_score >= 45
            scale_out = target_progress >= 80 or exit_score < 38
            signals.append({
                "symbol": symbol,
                "scale_in_candidate": bool(scale_in),
                "scale_out_candidate": bool(scale_out),
                "suggested_scale_in_pct": 10.0 if scale_in else 0.0,
                "suggested_scale_out_pct": 25.0 if scale_out else 0.0,
                "reason": "conviction_confirmed_shadow" if scale_in else ("target_or_exit_risk_shadow" if scale_out else "hold_size_shadow"),
                "risk_warning": "shadow_only_no_order_execution",
            })
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_first",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "scale_in_out_shadow_status_v1": True,
            "scale_signals": signals,
            "scale_in_candidate": any(s["scale_in_candidate"] for s in signals),
            "scale_out_candidate": any(s["scale_out_candidate"] for s in signals),
            "scale_in_candidate_count": sum(1 for s in signals if s["scale_in_candidate"]),
            "scale_out_candidate_count": sum(1 for s in signals if s["scale_out_candidate"]),
            "suggested_scale_in_pct": max([s["suggested_scale_in_pct"] for s in signals] or [0.0]),
            "suggested_scale_out_pct": max([s["suggested_scale_out_pct"] for s in signals] or [0.0]),
            "reason": "shadow sizing adjustments only; no orders are created",
            "risk_warning": "do_not_execute_without_future_explicit_policy_promotion",
            "promotion_allowed": False,
            "live_trading_changed": False,
            "broker_execution_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(80.0, 25.0 + len(signals) * 5.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "review_scale_signals_in_shadow_before_any_position_policy_change",
        }
