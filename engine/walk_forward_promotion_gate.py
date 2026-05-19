from __future__ import annotations

import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class WalkForwardPromotionGate:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl") + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl")
        returns = [_to_float(r.get("realized_return_pct"), _to_float(r.get("return_pct"), _to_float(r.get("pnl_pct"), 0.0))) for r in rows if any(k in r for k in ("realized_return_pct", "return_pct", "pnl_pct"))]
        windows = []
        if returns:
            size = max(5, min(50, len(returns) // 4 or 5))
            for i in range(0, len(returns), size):
                chunk = returns[i:i + size]
                if chunk:
                    windows.append(statistics.fmean(chunk))
        out_score = max(0.0, min(100.0, 50.0 + (statistics.fmean(windows[-2:]) * 3.0 if windows else 0.0)))
        stability = 100.0 - min(100.0, statistics.pstdev(windows) * 5.0) if len(windows) > 1 else 35.0 if returns else 0.0
        overfit = "high" if len(windows) < 3 else "moderate" if stability < 65 else "low"
        passed = bool(len(windows) >= 3 and out_score >= 55 and stability >= 55)
        failed = not passed
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "walk_forward_promotion_gate_status_v1": True,
            "passed_walk_forward": passed,
            "failed_walk_forward": failed,
            "out_of_sample_score": round(out_score, 3),
            "stability_score": round(stability, 3),
            "overfit_risk": overfit,
            "windows_evaluated": len(windows),
            "sample_size": len(returns),
            "promotion_recommendation": "do_not_promote_shadow_recommendations" if failed else "eligible_for_manual_research_review_only",
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "confidence_score": round(min(80.0, 15.0 + len(windows) * 12.0), 3),
            "generated_at": _now_iso(),
            "next_recommended_action": "require_more_unseen_data_before_any_future_manual_promotion",
        }
