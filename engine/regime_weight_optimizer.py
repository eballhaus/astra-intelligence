from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import BASELINE_WEIGHTS, _read_json, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(0.0, _to_float(v)) for v in weights.values()) or 100.0
    return {k: round(max(0.0, _to_float(v)) * 100.0 / total, 3) for k, v in weights.items()}


def _variant(**deltas: float) -> dict[str, float]:
    weights = dict(BASELINE_WEIGHTS)
    for key, delta in deltas.items():
        if key in weights:
            weights[key] += float(delta)
    return _normalize(weights)


class RegimeWeightOptimizer:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def _current_regime(self, context: dict[str, Any]) -> str:
        for source in (context, _read_json(f"{self.state_dir}/learning_insights_last_good.json"), _read_json(f"{self.state_dir}/snapshots/stable_top_buys_v1.json")):
            for key in ("current_regime", "market_regime", "regime", "market_status"):
                value = str((source or {}).get(key) or "").strip().lower()
                if value:
                    if "closed" in value or "weekend" in value or "after" in value:
                        return "after_hours_weekend_mode"
                    if "volatile" in value or "high_vol" in value:
                        return "high_volatility_market"
                    if "bull" in value or "risk-on" in value:
                        return "bull_market"
                    if "chop" in value or "range" in value:
                        return "choppy_market"
                    return value.replace(" ", "_")
        return "after_hours_weekend_mode"

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        context = context if isinstance(context, dict) else {}
        current = self._current_regime(context)
        best_by_regime = {
            "bull_market": _variant(expected_return_pct=3, conviction_10r=2, confidence=-2, psychology_brain=-1, grade_astra_score=-2),
            "choppy_market": _variant(entry_quality_v3=3, confidence=2, rank_persistence=2, expected_return_pct=-4, conviction_10r=-1, multi_brain_consensus=-2),
            "high_volatility_market": _variant(psychology_brain=3, entry_quality_v3=2, confidence=2, expected_return_pct=-3, conviction_10r=-2, grade_astra_score=-2),
            "small_cap_momentum_market": _variant(expected_return_pct=4, conviction_10r=2, multi_brain_consensus=1, confidence=-2, rank_persistence=-2, grade_astra_score=-3),
            "after_hours_weekend_mode": _variant(rank_persistence=4, confidence=2, entry_quality_v3=1, expected_return_pct=-3, conviction_10r=-2, psychology_brain=-2),
        }
        selected = best_by_regime.get(current, dict(BASELINE_WEIGHTS))
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "regime_weight_optimizer_status_v1": True,
            "current_regime": current,
            "baseline_weights": dict(BASELINE_WEIGHTS),
            "best_shadow_weights_by_regime": best_by_regime,
            "best_regime_weights": selected,
            "regime_confidence": 58.0 if current == "after_hours_weekend_mode" else 62.0,
            "confidence_score": 58.0 if current == "after_hours_weekend_mode" else 62.0,
            "regime_sample_size": int(_to_float(context.get("sample_size"), 0.0)),
            "recommended_regime_adjustments": [
                "keep regime weights shadow-only",
                f"test {current} weights against newer out-of-sample rows before promotion",
            ],
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "accumulate regime-labeled outcomes before any manual promotion review",
        }
