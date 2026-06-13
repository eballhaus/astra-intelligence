from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, VERSION, clamp, now_iso, pick_max, pick_min, rounded, safe_average, status_score, with_safety


class ConfidenceDecompositionEngineV1(CachedDiagnosticModule):
    module_name = "confidence_decomposition_engine_v1"
    mode = "shadow_analysis_confidence_decomposition"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        components = {
            "symbol_confidence": status_score(statuses, "accelerated_learning_symbol_intelligence_suite_v1", ["transferable_learning_confidence", "symbol_personality_quality_score"], 50.0),
            "catalyst_confidence": status_score(statuses, "catalyst_lifecycle_intelligence_v1", ["catalyst_lifecycle_confidence"], 50.0),
            "sector_confidence": status_score(statuses, "etf_sector_rotation_intelligence_v1", ["sector_rotation_confidence"], 50.0),
            "regime_confidence": status_score(statuses, "market_condition_attribution_v1", ["condition_confidence_score"], 50.0),
            "ranking_confidence": status_score(statuses, "candidate_ranking_attribution_promotion_intelligence_v1", ["ranking_confidence_score", "ranking_predictive_power"], 50.0),
            "historical_confidence": status_score(statuses, "historical_intelligence_market_memory_suite_v1", ["market_memory_quality_score", "confidence"], 50.0),
            "cross_market_confidence": status_score(statuses, "cross_market_attribution_transfer_learning_v1", ["cross_market_transfer_confidence", "cross_market_alpha_confidence"], 50.0),
            "profit_capture_confidence": status_score(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", ["policy_confidence", "profit_capture_score"], 50.0),
        }
        rows = [{"component": key, "score": rounded(value, 3)} for key, value in components.items()]
        weakest = pick_min(rows, "score")
        strongest = pick_max(rows, "score")
        overall = clamp(safe_average(list(components.values()), 50.0))
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            **{key: rounded(value, 3) for key, value in components.items()},
            "overall_confidence": rounded(overall, 3),
            "components": rows,
            "weakest_component": weakest.get("component", "insufficient_data"),
            "strongest_component": strongest.get("component", "insufficient_data"),
            "confidence_bottleneck": weakest.get("component", "insufficient_data"),
            "confidence_explanation": f"Primary bottleneck is {weakest.get('component', 'insufficient_data')} while strongest support is {strongest.get('component', 'insufficient_data')}.",
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

