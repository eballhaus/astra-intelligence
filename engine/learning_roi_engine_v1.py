from __future__ import annotations

import time
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    VERSION,
    evidence_count_from,
    module_row,
    now_iso,
    pick_max,
    rounded,
    status_score,
    with_safety,
)


class LearningRoiEngineV1(CachedDiagnosticModule):
    module_name = "learning_roi_engine_v1"
    mode = "shadow_analysis_learning_roi"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        rows = [
            module_row(statuses, "Trade Lifecycle Learning", "trade_lifecycle_excursion_v2", ["closed_trade_count", "lifecycles_tracked", "evidence_count"], ["lifecycle_quality_score", "exit_quality_score"], ["capture_ratio", "profit_capture_score"], "high"),
            module_row(statuses, "Replay Learning", "replay_counterfactual_learning_v2", ["replay_count", "counterfactual_count", "evidence_count"], ["replay_confidence", "readiness_score"], ["profit_capture_score"], "high"),
            module_row(statuses, "Shadow Learning", "realistic_shadow_evidence_learning_lab_v1", ["shadow_learning_events", "realism_weighted_learning_events", "virtual_paths_created"], ["average_shadow_realism_score", "evidence_quality_score"], ["shadow_capture_ratio"], "high"),
            module_row(statuses, "Candidate Ranking Attribution", "candidate_ranking_attribution_promotion_intelligence_v1", ["evidence_count", "top_ranked_candidates", "promoted_candidates"], ["ranking_quality_score", "ranking_predictive_power"], ["promotion_accuracy"], "high"),
            module_row(statuses, "Trade Family Intelligence", "trade_family_intelligence_v1", ["evidence_count", "family_count"], ["family_learning_score", "family_transfer_confidence"], ["family_profit_factor"], "medium"),
            module_row(statuses, "Catalyst Intelligence", "catalyst_lifecycle_intelligence_v1", ["evidence_count", "catalysts_tracked"], ["catalyst_lifecycle_confidence", "continuation_probability"], ["profitability_by_lifecycle_stage"], "high"),
            module_row(statuses, "Market Condition Attribution", "market_condition_attribution_v1", ["evidence_count", "condition_count"], ["condition_confidence_score"], ["profit_capture_by_condition"], "medium"),
            module_row(statuses, "Cross Market Attribution", "cross_market_attribution_transfer_learning_v1", ["relationship_count", "evidence_count"], ["cross_market_transfer_confidence", "cross_market_alpha_confidence"], ["cross_market_alpha_available"], "medium"),
            module_row(statuses, "Profit Capture Intelligence", "profit_capture_peak_decay_exit_validation_suite_v1", ["evidence_count", "completed_lifecycles"], ["policy_confidence", "profit_capture_score"], ["capture_ratio", "shadow_capture_ratio"], "highest"),
            module_row(statuses, "Opportunity Cost Learning", "opportunity_cost_learning", ["selected_candidates_reviewed", "rejected_candidates_reviewed", "evidence_count"], ["selection_quality_score", "ranking_quality_score"], ["missed_opportunity_score"], "high"),
        ]
        best = pick_max(rows, "confidence_level")
        raw_evidence = evidence_count_from(statuses)
        payload = {
            "enabled": True,
            "version": VERSION,
            "status": "ok" if rows else "insufficient_evidence",
            "mode": self.mode,
            "generated_at": now_iso(),
            "subsystems": rows,
            "subsystem_count": len(rows),
            "evidence_count": int(raw_evidence),
            "highest_value_learning_system": best.get("subsystem_name", "insufficient_data"),
            "highest_value_learning_confidence": rounded(best.get("confidence_level"), 3),
            "lowest_priority_learning_system": pick_max([row for row in rows if row.get("recommended_priority") == "monitor"] or rows, "evidence_count").get("subsystem_name", "insufficient_data"),
            "average_learning_roi_score": rounded(sum(float(row.get("confidence_level", 0.0)) for row in rows) / max(1, len(rows)), 3),
            "recommended_next_focus": "profit_capture_and_ranking_quality" if status_score(statuses, "profit_capture_peak_decay_exit_validation_suite_v1", ["profit_capture_score"], 50.0) < 65 else "ranking_tournament_validation",
            "build_ms": rounded((time.perf_counter() - start) * 1000.0, 3),
        }
        return with_safety(payload)

