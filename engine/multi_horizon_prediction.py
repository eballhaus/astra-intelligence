from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _stable_rows, _to_float
from engine.timeframe_target_zones import HORIZON_MULTIPLIERS, _zone

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _base_score(row: dict[str, Any]) -> float:
    return max(0.0, min(100.0,
        _to_float(row.get("opportunity_score_pct"), 55.0) * 0.30
        + _to_float(row.get("conviction_10r"), 60.0) * 0.20
        + _to_float(row.get("entry_quality_v3_score"), _to_float(row.get("entry_quality_score"), 55.0)) * 0.15
        + _to_float(row.get("confidence"), 55.0) * 0.15
        + _to_float(row.get("rank_stability_score"), 55.0) * 0.10
        + _to_float(row.get("multi_brain_score"), 55.0) * 0.05
        + _to_float(row.get("psychology_score"), 55.0) * 0.05
    ))


class MultiHorizonPredictionEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = rows if isinstance(rows, list) else _stable_rows(self.state_dir)
        predictions = []
        horizon_counts: dict[str, int] = {h: 0 for h in HORIZON_MULTIPLIERS}
        for row in rows[:12]:
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            base = _base_score(row)
            per_h = {}
            for h, mult in HORIZON_MULTIPLIERS.items():
                target = _zone(row, h)
                horizon_bias = {"1h": -6.0, "1d": -2.0, "3d": 2.5, "1w": 4.0, "1m": 1.5}[h]
                liquidity_penalty = max(0.0, _to_float(row.get("spread_risk"), 0.0) * (1.4 if h == "1h" else 0.5))
                score = max(0.0, min(100.0, base * (0.82 + mult * 0.18) + horizon_bias - liquidity_penalty))
                per_h[h] = {
                    "horizon_score": round(score, 3),
                    "expected_return_pct": target["expected_return_pct"],
                    "target_low": target["target_low"],
                    "target_mid": target["target_mid"],
                    "target_high": target["target_high"],
                    "probability_score": round(min(100.0, score * 0.92 + _to_float(row.get("confidence"), 50.0) * 0.08), 3),
                    "confidence": round(min(95.0, _to_float(row.get("confidence"), 50.0)), 3),
                    "risk_score": round(max(0.0, 100.0 - score), 3),
                }
            best = max(per_h, key=lambda h: per_h[h]["horizon_score"])
            horizon_counts[best] += 1
            style = "intraday" if best == "1h" else "day_trade" if best == "1d" else "swing" if best in {"3d", "1w"} else "position_trade"
            predictions.append({
                "symbol": symbol,
                "timeframes": per_h,
                "best_horizon_label": best,
                "recommended_hold_style": style,
                "best_horizon_score": per_h[best]["horizon_score"],
            })
        best_horizon = max(horizon_counts, key=lambda h: horizon_counts[h]) if predictions else "n/a"
        avg_score = statistics.fmean([p["best_horizon_score"] for p in predictions]) if predictions else 0.0
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "multi_horizon_prediction_status_v1": True,
            "predictions": predictions,
            "best_horizon_summary": {
                "best_horizon_detected": best_horizon,
                "average_best_horizon_score": round(avg_score, 3),
                "horizon_counts": horizon_counts,
            },
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(85.0, 28.0 + len(predictions) * 6.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "use_horizon_scores_for_shadow_review_only",
        }
