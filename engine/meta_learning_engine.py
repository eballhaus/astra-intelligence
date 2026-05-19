from __future__ import annotations

import math
import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_json, _read_jsonl, _stable_rows, _to_float

VERSION = "1.0.0"

FACTOR_FIELDS = {
    "expected_return_pct": ["expected_return_pct"],
    "conviction_5r": ["conviction_5r", "rolling_conviction_5r"],
    "conviction_10r": ["conviction_10r", "rolling_conviction_10r"],
    "conviction_20r": ["conviction_20r", "rolling_conviction_20r"],
    "entry_quality_v3": ["entry_quality_v3_score", "entry_quality_score"],
    "confidence": ["confidence"],
    "grade_astra_score": ["astra_composite_score", "opportunity_score_pct", "grade_percent"],
    "rank_persistence": ["rank_stability_score", "stable_age_seconds", "time_in_top_6_seconds"],
    "multi_brain_consensus": ["multi_brain_score", "multi_brain_agreement"],
    "psychology_brain": ["psychology_score"],
    "opportunity_score": ["opportunity_score_pct", "profit_priority_score"],
    "target_zone_accuracy": ["target_accuracy_score"],
    "exit_quality": ["exit_quality_score", "exit_score"],
}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _first_number(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            value = _to_float(row.get(key), math.nan)
            if math.isfinite(value):
                return value
    return None


def _outcome(row: dict[str, Any]) -> float | None:
    for key in ("realized_return_pct", "return_pct", "pnl_pct", "target_accuracy_score", "exit_quality_score"):
        if key in row and row.get(key) not in (None, ""):
            value = _to_float(row.get(key), math.nan)
            if math.isfinite(value):
                return value
    return None


def _corr(xs: list[float], ys: list[float]) -> float:
    if len(xs) < 4 or len(ys) < 4:
        return 0.0
    try:
        mx = statistics.fmean(xs)
        my = statistics.fmean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
        den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
        if den_x <= 0 or den_y <= 0:
            return 0.0
        return num / (den_x * den_y)
    except Exception:
        return 0.0


class MetaLearningEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        lifecycle = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl", limit=2500)
        labels = _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl", limit=2500)
        stable = _stable_rows(self.state_dir)
        rows = lifecycle + labels + stable
        factor_scores: list[dict[str, Any]] = []
        for name, keys in FACTOR_FIELDS.items():
            xs: list[float] = []
            ys: list[float] = []
            for row in rows:
                x = _first_number(row, keys)
                y = _outcome(row)
                if x is None or y is None:
                    continue
                xs.append(x)
                ys.append(y)
            corr = _corr(xs, ys)
            factor_scores.append({
                "factor": name,
                "predictive_score": round(abs(corr) * 100.0, 3),
                "direction": "positive" if corr >= 0 else "negative",
                "sample_size": len(xs),
            })
        factor_scores.sort(key=lambda r: (r["predictive_score"], r["sample_size"]), reverse=True)
        top = factor_scores[:5]
        weak = [f for f in factor_scores if f["sample_size"] > 0 and f["predictive_score"] < 8.0][:5]
        redundant = []
        names = {f["factor"] for f in factor_scores if f["sample_size"] > 0}
        if {"confidence", "grade_astra_score", "opportunity_score"}.issubset(names):
            redundant.append({"factor_group": ["confidence", "grade_astra_score", "opportunity_score"], "reason": "overlap should be checked before increasing all three weights"})
        ledger = _read_json(f"{self.state_dir}/learning_ledger_state.json")
        sample_size = len(rows) + int(_to_float(ledger.get("eligible_learning_rows"), 0.0))
        confidence = min(88.0, 20.0 + min(sample_size, 400) * 0.12 + len(top) * 2.0)
        improvement = min(10.0, max(0.0, (top[0]["predictive_score"] if top else 0.0) / 18.0)) if sample_size >= 10 else 0.0
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "meta_learning_status_v1": True,
            "top_predictive_factors": top,
            "weak_predictive_factors": weak,
            "redundant_factors": redundant,
            "recommended_shadow_adjustments": [
                f"prioritize {top[0]['factor']} in shadow tests" if top else "collect more labeled outcomes before changing weights",
                "do not promote until horizon shadow validation passes",
            ],
            "confidence": round(confidence, 3),
            "confidence_score": round(confidence, 3),
            "sample_size": int(sample_size),
            "improvement_opportunity": round(improvement, 3),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_rankings_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "keep_meta_learning_shadow_only_until_out_of_sample_validation_improves",
        }
