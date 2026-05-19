from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class IntradayIntelligenceEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        rows = rows if isinstance(rows, list) else _stable_rows(self.state_dir)
        candidates = []
        day_count = 0
        scalp_count = 0
        for row in rows[:12]:
            symbol = str(row.get("symbol") or row.get("ticker") or "").upper()
            volume_score = _to_float(row.get("volume_pressure_score"), _to_float(row.get("volume_score"), 50.0))
            momentum = _to_float(row.get("momentum_score"), _to_float(row.get("opportunity_score_pct"), 50.0))
            confidence = _to_float(row.get("confidence"), 50.0)
            spread_risk = _to_float(row.get("spread_risk"), 20.0)
            reversal_risk = _to_float(row.get("reversal_risk"), _to_float(row.get("chase_risk"), 35.0))
            score = max(0.0, min(100.0, momentum * 0.32 + volume_score * 0.24 + confidence * 0.22 + (100 - spread_risk) * 0.12 + (100 - reversal_risk) * 0.10))
            setup = "volume_surge_continuation" if volume_score >= 70 else "vwap_reclaim_or_pullback" if momentum >= 65 else "watch_for_confirmation"
            day = bool(score >= 68 and spread_risk <= 45)
            scalp = bool(score >= 88 and spread_risk <= 20 and volume_score >= 80)
            day_count += int(day)
            scalp_count += int(scalp)
            candidates.append({
                "symbol": symbol,
                "intraday_score": round(score, 3),
                "intraday_setup_type": setup,
                "intraday_confidence": round(min(95.0, confidence * 0.75 + score * 0.25), 3),
                "intraday_risk_label": "low" if spread_risk <= 20 and reversal_risk <= 30 else "moderate" if score >= 65 else "elevated",
                "scalp_candidate": scalp,
                "day_trade_candidate": day,
                "invalid_intraday_reason": "" if day else "needs stronger liquidity, momentum, or confirmation",
                "suggested_intraday_hold_window": "30-120 minutes" if day else "wait_for_confirmation",
                "exit_urgency": "high" if reversal_risk >= 70 else "normal",
            })
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "intraday_intelligence_status_v1": True,
            "intraday_candidates": candidates,
            "intraday_summary": {
                "symbols_evaluated": len(candidates),
                "day_trade_candidate_count": day_count,
                "scalp_candidate_count": scalp_count,
                "best_intraday_candidate": max(candidates, key=lambda c: c["intraday_score"]) if candidates else {},
            },
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(82.0, 25.0 + len(candidates) * 5.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "keep_intraday_and_scalp_labels_informational_only",
        }
