from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    clamp,
    evidence_count_from,
    now_iso,
    rounded,
    safe_average,
    status_score,
    status_value,
    to_int,
    with_safety,
)


class EvidenceQualityScoringV1(CachedDiagnosticModule):
    module_name = "evidence_quality_scoring_v1"
    mode = "shadow_analysis_evidence_quality"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        raw = evidence_count_from(statuses)
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        catalyst = status_value(statuses, "catalyst_lifecycle_intelligence_v1")
        market = status_value(statuses, "market_transition_detection_v1")
        lifecycle = status_value(statuses, "trade_lifecycle_excursion_v2")
        quality_factors = {
            "trade_type": status_score(statuses, "trade_family_intelligence_v1", ["family_learning_score"], 55.0),
            "volatility": status_score(statuses, "market_breadth_index_intelligence_v1", ["volatility_pressure_score"], 50.0),
            "catalyst_presence": status_score(statuses, "catalyst_lifecycle_intelligence_v1", ["catalyst_lifecycle_confidence"], 45.0),
            "rarity": min(100.0, max(35.0, raw / 60.0)),
            "regime_importance": status_score(statuses, "market_condition_attribution_v1", ["condition_confidence_score"], 50.0),
            "market_stress": status_score(statuses, "market_transition_detection_v1", ["transition_confidence"], 45.0),
            "transition_relevance": status_score(statuses, "market_transition_detection_v1", ["transition_risk_score"], 45.0),
            "recency": 72.0 if raw >= 100 else 45.0,
            "outcome_clarity": max(status_score(statuses, "shadow_vs_paper_performance_attribution_v1", ["paper_profit_factor_verified", "paper_win_rate"], 50.0), status_score(statuses, "candidate_ranking_attribution_promotion_intelligence_v1", ["ranking_predictive_power"], 50.0)),
        }
        average_quality = clamp(safe_average(list(quality_factors.values()), 0.0))
        weighted_count = raw * (0.35 + average_quality / 100.0)
        high_quality = int(weighted_count * 0.42)
        low_quality = max(0, raw - high_quality - int(weighted_count * 0.18))
        if average_quality >= 72:
            bucket = "high_quality"
        elif average_quality >= 55:
            bucket = "mixed_quality"
        elif raw <= 0:
            bucket = "insufficient_evidence"
        else:
            bucket = "low_quality"
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if raw > 0 else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "raw_evidence_count": int(raw),
            "weighted_evidence_count": rounded(weighted_count, 3),
            "average_evidence_quality": rounded(average_quality, 3),
            "high_quality_evidence_count": int(high_quality),
            "low_quality_evidence_count": int(low_quality),
            "quality_bucket": bucket,
            "quality_reason": "weighted_by_catalyst_regime_recency_and_outcome_clarity",
            "quality_factors": {key: rounded(value, 3) for key, value in quality_factors.items()},
            "shadow_learning_events": to_int(shadow.get("shadow_learning_events"), 0),
            "catalysts_tracked": to_int(catalyst.get("evidence_count"), 0),
            "transition_risk_score": rounded(market.get("transition_risk_score"), 3),
            "closed_lifecycle_count": to_int(lifecycle.get("closed_trade_count"), 0),
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

