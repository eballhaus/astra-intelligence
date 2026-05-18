"""Expected Return Engine V1.

Snapshot-only expected return estimates for displayed opportunities. This module
uses fields already present on candidate rows and never calls providers.
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
        return n if n == n and n not in (float("inf"), float("-inf")) else default
    except Exception:
        return default


def _first(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return None


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, float(value)))


class ExpectedReturnEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "snapshot_only_probability_adjusted"

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        src = dict(row or {})
        price = _f(_first(src, "current_price", "price", "live_price", "last_price", "close", "mark_price"), None)
        stop = _f(_first(src, "stop_loss", "stop", "stop_price", "invalidation_level"), None)
        if price is None or price <= 0:
            return {
                "expected_return_available": False,
                "expected_return_unavailable_reason": "missing_current_price",
            }
        conv10 = _f(_first(src, "conviction_10r", "rolling_conviction_10r", "conviction_display_score"), None)
        conv5 = _f(_first(src, "conviction_5r", "rolling_conviction_5r"), conv10 if conv10 is not None else None)
        conv20 = _f(_first(src, "conviction_20r", "rolling_conviction_20r"), conv10 if conv10 is not None else None)
        confidence = _f(_first(src, "confidence", "buy_confidence", "predicted_win_probability"), 50.0) or 50.0
        quality = _f(_first(src, "buy_quality_score", "trade_quality_score", "quality_score", "grade_percent"), 50.0) or 50.0
        entry = _f(_first(src, "entry_quality_v3_score", "entry_quality_v2_score", "entry_quality_score"), 50.0) or 50.0
        consensus = _f(_first(src, "multi_brain_agreement", "multi_brain_score", "consensus_score"), 50.0) or 50.0
        psychology = _f(_first(src, "psychology_score"), 60.0) or 60.0
        persistence = _f(_first(src, "persistence_score", "rank_stability_score", "stability_score"), 50.0) or 50.0
        regime = _f(_first(src, "market_regime_alignment", "regime_alignment_score"), 50.0) or 50.0
        existing_pct = _f(_first(src, "expected_move_percent", "expected_move_pct", "profit_prediction_pct", "predicted_return_pct"), None)
        if existing_pct is not None and abs(existing_pct) >= 0.05:
            mid_pct = max(0.0, existing_pct)
            method = "existing_candidate_expected_move_pct"
        else:
            signal = (
                (conv10 if conv10 is not None else quality) * 0.22
                + (conv5 if conv5 is not None else quality) * 0.08
                + (conv20 if conv20 is not None else quality) * 0.08
                + entry * 0.16
                + confidence * 0.14
                + quality * 0.12
                + consensus * 0.08
                + psychology * 0.05
                + persistence * 0.04
                + regime * 0.03
            )
            risk_pct = ((price - stop) / price * 100.0) if stop is not None and 0 < stop < price else 4.0
            risk_pct = max(1.0, min(12.0, risk_pct))
            momentum_bonus = max(0.0, signal - 55.0) * 0.09
            mid_pct = max(1.0, min(28.0, risk_pct * (1.15 + (signal / 100.0)) + momentum_bonus))
            method = "derived_from_conviction_quality_risk"
        uncertainty = max(1.0, min(8.0, mid_pct * 0.32))
        low_pct = max(0.25, mid_pct - uncertainty)
        high_pct = min(45.0, mid_pct + uncertainty * 1.35)
        target_low = price * (1.0 + low_pct / 100.0)
        target_mid = price * (1.0 + mid_pct / 100.0)
        target_high = price * (1.0 + high_pct / 100.0)
        risk_pct = ((price - stop) / price * 100.0) if stop is not None and 0 < stop < price else None
        reward_to_risk = (mid_pct / risk_pct) if risk_pct and risk_pct > 0 else None
        probability_factor = _clamp((confidence * 0.35 + (conv10 if conv10 is not None else quality) * 0.3 + entry * 0.2 + consensus * 0.1 + psychology * 0.05), 0, 100) / 100.0
        probability_adjusted = _clamp((mid_pct * probability_factor) * 3.2, 0, 100)
        if high_pct >= 12:
            zone_label = "high_upside_target_zone"
        elif high_pct >= 6:
            zone_label = "balanced_target_zone"
        else:
            zone_label = "tight_target_zone"
        return {
            "expected_return_available": True,
            "expected_return_method": method,
            "expected_return_pct": round(mid_pct, 3),
            "expected_return_low_pct": round(low_pct, 3),
            "expected_return_high_pct": round(high_pct, 3),
            "expected_target_low": round(target_low, 4),
            "expected_target_mid": round(target_mid, 4),
            "expected_target_high": round(target_high, 4),
            "expected_target_zone_label": zone_label,
            "estimated_reward_to_risk": round(reward_to_risk, 3) if reward_to_risk is not None else None,
            "probability_adjusted_return_score": round(probability_adjusted, 3),
            "target_unavailable_reason": "",
            "api_calls_used": 0,
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [self.score_row(r) for r in list(rows or []) if isinstance(r, dict)]
        available = [r for r in scored if r.get("expected_return_available")]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "expected_return_status_v1": True,
            "candidates_evaluated": len(scored),
            "expected_return_fields_populated": len(available),
            "average_expected_return_pct": round(sum(float(r.get("expected_return_pct") or 0) for r in available) / max(1, len(available)), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "use_expected_return_as_display_layer_without_changing_raw_strategy",
        }
