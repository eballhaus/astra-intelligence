"""Exit Averaging Engine V1.

Read-only exit deterioration and target-progress planner. It does not place
orders or alter broker/live execution behavior.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _f(value: Any, default: float | None = 0.0) -> float | None:
    try:
        n = float(value)
        return n if n == n else default
    except Exception:
        return default


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


class ExitAveragingEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "read_only_multi_cycle_exit_confirmation"

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        src = dict(row or {})
        price = _f(_first(src, "current_price", "price", "live_price", "last_price", "close", "mark_price"), None)
        stop = _f(_first(src, "stop_loss", "stop", "stop_price", "invalidation_level"), None)
        target_low = _f(_first(src, "target_1", "target_zone_low", "expected_target_low"), None)
        target_high = _f(_first(src, "stretch_target", "target_zone_high", "expected_target_high"), None)
        confidence = _f(src.get("confidence"), 50.0) or 50.0
        conv10 = _f(_first(src, "conviction_10r", "rolling_conviction_10r", "conviction_display_score"), 50.0) or 50.0
        psychology_risk = _f(_first(src, "psychology_chase_risk", "psychology_exhaustion_risk", "crowding_risk"), 35.0) or 35.0
        if price is None or price <= 0:
            return {"exit_score_available": False, "exit_unavailable_reason": "missing_current_price", "api_calls_used": 0}
        stop_pressure = 0.0
        if stop is not None and stop > 0:
            if price <= stop:
                stop_pressure = 100.0
            else:
                stop_pressure = max(0.0, 35.0 - ((price - stop) / price * 100.0) * 8.0)
        target_progress = None
        if stop is not None and target_low is not None and target_low > stop:
            target_progress = max(0.0, min(100.0, ((price - stop) / (target_low - stop)) * 100.0))
        deterioration = max(0.0, 70.0 - confidence) * 0.45 + max(0.0, 65.0 - conv10) * 0.35 + max(0.0, psychology_risk - 55.0) * 0.2
        exit_score = max(0.0, min(100.0, stop_pressure * 0.45 + deterioration * 0.55))
        averaged_exit_score = max(0.0, min(100.0, (exit_score * 0.55) + (_f(src.get("prior_exit_score"), exit_score) or exit_score) * 0.45))
        confirmation_count = int(_f(src.get("exit_confirmation_count"), 0.0) or 0)
        if averaged_exit_score >= 72:
            confirmation_count = max(confirmation_count, 2)
        elif averaged_exit_score >= 55:
            confirmation_count = max(confirmation_count, 1)
        else:
            confirmation_count = 0
        if stop is not None and price <= stop:
            label = "hard_stop_breach"
            sell_zone = "sell_immediately_hard_stop"
            reason = "hard_stop_breach"
        elif averaged_exit_score >= 72 and confirmation_count >= 2:
            label = "true_deterioration"
            sell_zone = "confirmed_sell_zone"
            reason = "multi_cycle_deterioration_confirmed"
        elif averaged_exit_score >= 55:
            label = "needs_confirmation"
            sell_zone = "watch_for_confirmation"
            reason = "deterioration_not_confirmed"
        else:
            label = "normal_pullback_or_continuation"
            sell_zone = "hold_with_trailing_stop"
            reason = "no_confirmed_exit_signal"
        trailing_stop = None
        if stop is not None:
            trailing_stop = max(stop, price * 0.96 if label == "normal_pullback_or_continuation" else price * 0.975)
        return {
            "exit_score_available": True,
            "exit_score": round(exit_score, 3),
            "averaged_exit_score": round(averaged_exit_score, 3),
            "exit_confirmation_count": confirmation_count,
            "pullback_vs_breakdown_label": label,
            "trailing_stop_price": round(trailing_stop, 4) if trailing_stop is not None else None,
            "profit_protection_status": sell_zone,
            "recommended_sell_zone": sell_zone,
            "sell_reason": reason,
            "target_progress_pct": round(target_progress, 3) if target_progress is not None else None,
            "target_hit_status": "target_zone_reached" if target_low is not None and price >= target_low else "target_not_reached",
            "sell_immediately_only_on_hard_invalidation": True,
            "api_calls_used": 0,
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [self.score_row(r) for r in list(rows or []) if isinstance(r, dict)]
        available = [r for r in scored if r.get("exit_score_available")]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "exit_averaging_status_v1": True,
            "candidates_evaluated": len(scored),
            "exit_scores_available": len(available),
            "average_exit_score": round(sum(float(r.get("exit_score") or 0) for r in available) / max(1, len(available)), 3),
            "immediate_sell_requires_hard_invalidation": True,
            "multi_cycle_confirmation_required": True,
            "generated_at": _now_iso(),
            "next_recommended_action": "use_averaged_exit_status_for_monitoring_without_order_execution",
        }
