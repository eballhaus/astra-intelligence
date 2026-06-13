from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, VERSION, clamp, first, now_iso, rounded, status_score, status_value, text, with_safety


class MarketRegimeSimilarityEngineV1(CachedDiagnosticModule):
    module_name = "market_regime_similarity_engine_v1"
    mode = "shadow_analysis_market_regime_similarity"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        breadth = status_value(statuses, "market_breadth_index_intelligence_v1")
        etf = status_value(statuses, "etf_sector_rotation_intelligence_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        cross = status_value(statuses, "cross_market_attribution_transfer_learning_v1")
        signature = {
            "index_regime": text(first(breadth.get("current_index_regime"), transition.get("current_market_phase"), default="unknown")),
            "strongest_sector": text(etf.get("strongest_sector"), "unknown"),
            "risk_on_score": rounded(breadth.get("risk_on_score"), 3),
            "risk_off_score": rounded(breadth.get("risk_off_score"), 3),
            "volatility_pressure_score": rounded(breadth.get("volatility_pressure_score"), 3),
            "transition_risk_score": rounded(transition.get("transition_risk_score"), 3),
            "market_psychology_score": rounded(cross.get("market_psychology_score"), 3),
        }
        risk_on = status_score(statuses, "market_breadth_index_intelligence_v1", ["risk_on_score"], 50.0)
        transition_risk = status_score(statuses, "market_transition_detection_v1", ["transition_risk_score"], 45.0)
        vol = status_score(statuses, "market_breadth_index_intelligence_v1", ["volatility_pressure_score"], 45.0)
        periods = [
            {"period": "momentum_expansion_analog", "similarity_score": clamp(70 + risk_on * 0.20 - transition_risk * 0.10), "matching_features": ["QQQ/SPY support", "growth continuation", "risk-on breadth"], "historical_outcome_summary": "momentum names tended to continue but profit capture still mattered"},
            {"period": "rotation_market_analog", "similarity_score": clamp(58 + transition_risk * 0.25), "matching_features": ["sector rotation", "leadership transition", "breadth divergence"], "historical_outcome_summary": "sector leadership changed quickly and stale leaders gave back gains"},
            {"period": "volatility_compression_breakout_analog", "similarity_score": clamp(55 + vol * 0.25), "matching_features": ["volatility pressure", "transition risk", "continuation uncertainty"], "historical_outcome_summary": "breakouts required tighter confirmation and faster review"},
        ]
        top = max(periods, key=lambda row: row["similarity_score"])
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "current_regime_signature": signature,
            "top_similar_periods": [{**row, "similarity_score": rounded(row["similarity_score"], 3)} for row in periods],
            "similarity_score": rounded(top["similarity_score"], 3),
            "matching_features": top["matching_features"],
            "historical_outcome_summary": top["historical_outcome_summary"],
            "confidence": rounded(clamp((top["similarity_score"] + status_score(statuses, "market_condition_attribution_v1", ["condition_confidence_score"], 50.0)) / 2.0), 3),
            "most_similar_regime": top["period"],
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

