from __future__ import annotations

import collections
import statistics
from datetime import UTC, datetime
from typing import Any

from engine.adaptive_weight_optimizer import _read_jsonl, _stable_rows, _to_float

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _bucket(row: dict[str, Any]) -> str:
    setup = str(row.get("setup_type") or row.get("strategy_family") or row.get("persona") or row.get("opportunity_grade") or "general_momentum").strip()
    regime = str(row.get("regime") or row.get("market_regime") or "mixed_regime").strip()
    return f"{setup or 'general'} / {regime or 'mixed'}"


class StrategyScorecardEngine:
    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")

    def status(self, context: dict[str, Any] | None = None) -> dict[str, Any]:
        rows = _read_jsonl(f"{self.state_dir}/trade_lifecycle_v1.jsonl") + _read_jsonl(f"{self.state_dir}/outcome_labels_v1.jsonl")
        if not rows:
            rows = _stable_rows(self.state_dir)
        groups: dict[str, list[float]] = collections.defaultdict(list)
        for row in rows:
            score = _to_float(row.get("realized_return_pct"), _to_float(row.get("opportunity_score_pct"), _to_float(row.get("confidence"), 50.0)))
            groups[_bucket(row)].append(score)
        scored = []
        for name, vals in groups.items():
            scored.append({
                "strategy": name,
                "sample_size": len(vals),
                "score": round(statistics.fmean(vals), 3) if vals else 0.0,
            })
        scored.sort(key=lambda x: (x["score"], x["sample_size"]), reverse=True)
        best = scored[:3]
        weakest = sorted(scored, key=lambda x: (x["score"], -x["sample_size"]))[:3]
        confidence = min(85.0, 20.0 + sum(x["sample_size"] for x in scored[:8]) * 0.25)
        return {
            "enabled": True,
            "version": VERSION,
            "mode": "shadow_only",
            "local_only": True,
            "writes_files": False,
            "api_calls_used": 0,
            "strategy_scorecard_status_v1": True,
            "best_strategies": best,
            "weakest_strategies": weakest,
            "strategies_to_watch": [x for x in scored[3:6]],
            "strategies_to_suppress_shadow": weakest if len(rows) >= 20 else [],
            "scorecard_confidence": round(confidence, 3),
            "confidence_score": round(confidence, 3),
            "sample_size": len(rows),
            "top_strategy": (best[0]["strategy"] if best else "collect_more_strategy_outcomes"),
            "promotion_allowed": False,
            "live_trading_changed": False,
            "production_weights_changed": False,
            "paper_trading_changed": False,
            "generated_at": _now_iso(),
            "next_recommended_action": "use_scorecard_for_shadow_research_prioritization_only",
        }
