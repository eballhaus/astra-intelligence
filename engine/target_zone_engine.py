"""Target Zone Engine V1."""
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


class TargetZoneEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.mode = "snapshot_target_zone_estimates"

    def score_row(self, row: dict[str, Any]) -> dict[str, Any]:
        src = dict(row or {})
        price = _f(_first(src, "current_price", "price", "live_price", "last_price", "close", "mark_price"), None)
        stop = _f(_first(src, "stop_loss", "stop", "stop_price", "invalidation_level"), None)
        low = _f(src.get("expected_target_low"), None)
        mid = _f(src.get("expected_target_mid"), None)
        high = _f(src.get("expected_target_high"), None)
        if price is None or price <= 0:
            return {"target_zone_available": False, "target_unavailable_reason": "missing_current_price", "api_calls_used": 0}
        pct = _f(src.get("expected_return_pct"), None)
        if (low is None or mid is None or high is None) and pct is not None:
            low = price * (1.0 + max(0.25, pct * 0.68) / 100.0)
            mid = price * (1.0 + pct / 100.0)
            high = price * (1.0 + max(pct * 1.38, pct + 1.0) / 100.0)
        if low is None or mid is None or high is None:
            return {"target_zone_available": False, "target_unavailable_reason": "insufficient_expected_return_inputs", "api_calls_used": 0}
        risk = (price - stop) if stop is not None and 0 < stop < price else None
        theoretical = {}
        if risk is not None and risk > 0:
            theoretical = {
                "theoretical_target_5r": round(price + risk * 5.0, 4),
                "theoretical_target_10r": round(price + risk * 10.0, 4),
                "theoretical_target_20r": round(price + risk * 20.0, 4),
            }
        return {
            "target_zone_available": True,
            "target_1": round(low, 4),
            "target_2": round(mid, 4),
            "stretch_target": round(high, 4),
            "target_zone_low": round(low, 4),
            "target_zone_high": round(high, 4),
            "target_zone_display": f"${low:.2f}-${high:.2f}",
            "target_zone_label": src.get("expected_target_zone_label") or "probability_adjusted_target_zone",
            "target_unavailable_reason": "",
            **theoretical,
            "api_calls_used": 0,
        }

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        scored = [self.score_row(r) for r in list(rows or []) if isinstance(r, dict)]
        available = [r for r in scored if r.get("target_zone_available")]
        return {
            "enabled": True,
            "version": VERSION,
            "mode": self.mode,
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "target_zone_status_v1": True,
            "candidates_evaluated": len(scored),
            "target_zones_available": len(available),
            "target_zones_unavailable": len(scored) - len(available),
            "generated_at": _now_iso(),
            "next_recommended_action": "display_practical_target_zone_and_keep_theoretical_r_targets_in_details",
        }
