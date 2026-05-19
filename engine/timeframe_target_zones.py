from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _stable_rows, _to_float

VERSION = "1.0.0"
HORIZON_MULTIPLIERS = {"1h": 0.12, "1d": 0.35, "3d": 0.62, "1w": 0.82, "1m": 1.0}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _price(row: dict[str, Any]) -> float:
    return _to_float(row.get("current_price"), _to_float(row.get("price"), _to_float(row.get("last_price"), 0.0)))


def _expected_return(row: dict[str, Any]) -> float:
    return max(0.0, _to_float(row.get("expected_return_pct"), _to_float(row.get("opportunity_score_pct"), 50.0) / 8.0))


def _zone(row: dict[str, Any], horizon: str) -> dict[str, Any]:
    px = _price(row)
    exp = _expected_return(row) * HORIZON_MULTIPLIERS[horizon]
    low = px * (1.0 + exp * 0.65 / 100.0) if px > 0 else None
    mid = px * (1.0 + exp / 100.0) if px > 0 else None
    high = px * (1.0 + exp * 1.35 / 100.0) if px > 0 else None
    return {
        "horizon": horizon,
        "expected_return_pct": round(exp, 3),
        "target_low": round(low, 3) if low else None,
        "target_mid": round(mid, 3) if mid else None,
        "target_high": round(high, 3) if high else None,
    }


class TimeframeTargetZones:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def rows(self) -> list[dict[str, Any]]:
        return _stable_rows(self.state_dir)

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = rows if isinstance(rows, list) else self.rows()
        symbols = []
        best_returns = []
        for row in rows[:12]:
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            zones = {h: _zone(row, h) for h in HORIZON_MULTIPLIERS}
            best_h = max(zones, key=lambda h: zones[h]["expected_return_pct"])
            best = zones[best_h]
            best_returns.append(best["expected_return_pct"])
            symbols.append({
                "symbol": symbol,
                "target_1h": zones["1h"],
                "target_1d": zones["1d"],
                "target_3d": zones["3d"],
                "target_1w": zones["1w"],
                "target_1m": zones["1m"],
                "best_target_zone": best,
                "conservative_target": best.get("target_low"),
                "stretch_target": best.get("target_high"),
                "target_confidence": round(min(90.0, 35.0 + _to_float(row.get("confidence"), 50.0) * 0.35), 3),
                "target_reason": "timeframe targets scaled from existing expected-return and target-zone snapshots",
            })
        avg = statistics.fmean(best_returns) if best_returns else 0.0
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "timeframe_target_zones_status_v1": True,
            "symbols_evaluated": len(symbols),
            "timeframes": list(HORIZON_MULTIPLIERS.keys()),
            "target_zones": symbols,
            "timeframe_target_summary": {
                "symbols_evaluated": len(symbols),
                "average_best_expected_return_pct": round(avg, 3),
                "best_target_zone": symbols[0].get("best_target_zone") if symbols else {},
            },
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(85.0, 30.0 + len(symbols) * 6.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "display_targets_as_shadow_guidance_only",
        }
