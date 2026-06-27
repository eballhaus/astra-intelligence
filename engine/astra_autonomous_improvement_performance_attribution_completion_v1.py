from __future__ import annotations

import os
from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    first,
    now_iso,
    rounded,
    status_value,
    text,
    to_float,
    to_int,
    with_safety,
)

STATE_SCAN_LIMIT = 80
LARGE_STATE_BYTES = 50_000_000
CRITICAL_STATE_BYTES = 750_000_000


def _safety_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "shadow_analysis_mode": True,
        "advisory_only": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "promotion_logic_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
        "paper_execution_changed": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "automatic_promotions_enabled": False,
        "automatic_learned_exits_enabled": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
    }


def _safe_list(value: Any, limit: int = 8) -> list[Any]:
    if isinstance(value, list):
        return value[:limit]
    if value in (None, ""):
        return []
    return [value]


class AstraAutonomousImprovementPerformanceAttributionCompletionV1(CachedDiagnosticModule):
    """Advisory completion layer for autonomous improvement attribution.

    This module intentionally consumes existing cached Astra diagnostics instead
    of rescanning raw trading archives. It ranks improvement opportunities,
    identifies performance/storage bottlenecks, and explains which attribution
    gaps should be completed before any future paper micro-test is considered.
    """

    module_name = "astra_autonomous_improvement_performance_attribution_completion_v1"
    mode = "autonomous_improvement_performance_attribution_completion_advisory"

    def _state_inventory(self) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        try:
            names = sorted(os.listdir(self.state_dir))[:STATE_SCAN_LIMIT]
        except Exception:
            names = []
        for name in names:
            path = os.path.join(self.state_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                stat = os.stat(path)
            except Exception:
                continue
            size = int(stat.st_size)
            rows.append({
                "name": name,
                "path": f"state/{name}",
                "size_bytes": size,
                "size_mb": rounded(size / 1_000_000.0, 3),
                "recommendation": "compress_or_archive_after_cached_truth_preserved" if size >= LARGE_STATE_BYTES else "retain",
            })
        rows.sort(key=lambda row: to_int(row.get("size_bytes"), 0), reverse=True)
        largest = rows[0] if rows else {}
        total = sum(to_int(row.get("size_bytes"), 0) for row in rows)
        pressure = clamp((to_float((largest or {}).get("size_bytes"), 0.0) / CRITICAL_STATE_BYTES) * 100.0)
        return {
            "state_files_reviewed": len(rows),
            "state_bytes_reviewed": total,
            "largest_state_file": largest,
            "large_state_files": [row for row in rows if to_int(row.get("size_bytes"), 0) >= LARGE_STATE_BYTES][:10],
            "storage_pressure_score": rounded(pressure, 3),
            "storage_issue": text((largest or {}).get("name"), "none") if pressure >= 50 else "within_current_bounds",
            "compaction_recommendation": "preserve_cached_truth_then_archive_large_append_only_files" if pressure >= 50 else "no_compaction_required_now",
        }

    def _performance_storage(self, statuses: dict[str, Any], optimization: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
        resource = optimization.get("resource_allocation_summary") or {}
        slowest = resource.get("slowest_endpoint") or {}
        bottlenecks = _safe_list(optimization.get("top_performance_bottlenecks"), 5)
        slow_name = text(first(slowest.get("system_name"), slowest.get("endpoint"), optimization.get("top_bottlenecks", [None])[0] if isinstance(optimization.get("top_bottlenecks"), list) else None), "full_opportunity_lifecycle_learning_suite_v1")
        slow_ms = rounded(first(slowest.get("latency_ms"), status_value(statuses, slow_name).get("build_ms"), 0.0), 3)
        lifecycle = status_value(statuses, "full_opportunity_lifecycle_learning_suite_v1")
        lifecycle_ms = rounded(lifecycle.get("build_ms"), 3)
        if lifecycle_ms > slow_ms:
            slow_name = "full_opportunity_lifecycle_learning_suite_v1"
            slow_ms = lifecycle_ms
        return {
            "status": "watch" if slow_ms >= 5000 or state.get("storage_pressure_score", 0) >= 50 else "ok",
            "slowest_system": slow_name,
            "slowest_system_latency_ms": slow_ms,
            "known_latency_watch": {
                "full_opportunity_lifecycle_learning_suite_v1_ms": lifecycle_ms,
                "watch_threshold_ms": 5000,
                "cache_first_fallback_required": lifecycle_ms >= 5000,
            },
            "slow_endpoint_ranking": bottlenecks,
            "storage_issue": state.get("storage_issue"),
            "storage_pressure_score": state.get("storage_pressure_score"),
            "largest_state_file": state.get("largest_state_file"),
            "large_state_files": state.get("large_state_files"),
            "dashboard_safety_guard": "use_cached_unified_payload_and_module_caches_before_heavy_scans",
            "recommendation": "cache_or_stale-while-revalidate_slowest_system_and_plan_state_compaction" if slow_ms >= 5000 or state.get("storage_pressure_score", 0) >= 50 else "retain_current_cache_policy",
        }

    def _ranking_attribution(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        controlled = status_value(statuses, "astra_controlled_ranking_evolution_executive_layer_v1")
        evidence = to_int(ranking.get("evidence_count"), 0)
        quality = rounded(first(ranking.get("ranking_quality_score"), ranking.get("attribution_quality"), 0.0), 3)
        confidence = rounded(first(ranking.get("confidence_score"), controlled.get("ranking_bias_horizon_tie_breaker_validation_v1", {}).get("confidence_score") if isinstance(controlled.get("ranking_bias_horizon_tie_breaker_validation_v1"), dict) else 0.0), 3)
        return {
            "status": "ok" if evidence >= 100 and confidence >= 50 else "insufficient_evidence",
            "ranking_attribution_score": quality,
            "ranking_confidence": confidence,
            "evidence_count": evidence,
            "why_candidate_a_ranked_above_b": "ranking_component_contributions_are_available" if evidence else "missing_candidate_level_evidence",
            "horizon_favored_reason": text(first(controlled.get("why_horizon_concentration_still_exists"), ranking.get("dominant_ranking_mistake"), "horizon_preference_requires_more_attribution")),
            "top_ranking_weaknesses": [
                text(ranking.get("dominant_ranking_blind_spot"), "opportunity_cost_context"),
                text(ranking.get("dominant_ranking_mistake"), "ranking_component_attribution_gap"),
                text(ranking.get("least_predictive_ranking_factor"), "least_predictive_factor_warming_up"),
            ],
            "top_ranking_strengths": [
                text(ranking.get("most_predictive_ranking_factor"), "confidence_score"),
                text(ranking.get("strongest_positive_ranking_factor"), "buy_purity_context"),
                text(ranking.get("strongest_promotion_archetype"), "promotion_archetype_warming_up"),
            ],
            "missed_candidate_findings": {
                "biggest_missed_promotion": ranking.get("biggest_missed_promotion"),
                "missed_winners": ranking.get("missed_winners"),
                "missed_alpha": ranking.get("missed_alpha"),
            },
            "next_ranking_improvement": text(first(ranking.get("highest_expected_ranking_improvement"), ranking.get("next_ranking_focus"), "complete_opportunity_cost_and_horizon_attribution")),
        }

    def _profit_capture(self, statuses: dict[str, Any]) -> dict[str, Any]:
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        profit = status_value(statuses, "profit_capture_peak_decay_exit_validation_suite_v1")
        lock = status_value(statuses, "profit_lock_profit_capture_maturation_v2")
        targeted = status_value(statuses, "astra_targeted_maturity_profit_capture_optimization_bundle_v1")
        capture = rounded(first(learned.get("baseline_capture_ratio"), profit.get("capture_ratio"), lock.get("capture_ratio"), targeted.get("profit_capture_score"), 0.0), 3)
        giveback = rounded(first(learned.get("baseline_giveback"), profit.get("avg_giveback"), lock.get("avg_giveback"), 0.0), 3)
        confidence = rounded(first(learned.get("policy_confidence"), profit.get("confidence_score"), lock.get("confidence_score"), 0.0), 3)
        evidence = max(to_int(learned.get("evidence_count"), 0), to_int(profit.get("evidence_count"), 0), to_int(lock.get("evidence_count"), 0))
        blockers = _safe_list(learned.get("paper_exit_path_blockers"), 8) + _safe_list(profit.get("profit_capture_blockers"), 8)
        ready = bool(confidence >= 65 and evidence >= 50 and not blockers and learned.get("learned_exit_bucket_enabled"))
        return {
            "status": "ready_for_review" if ready else "needs_investigation",
            "profit_capture_confidence": confidence,
            "profit_capture_evidence_count": evidence,
            "capture_ratio": capture,
            "average_giveback": giveback,
            "giveback_validation": "giveback_detected" if giveback > 0 else "warming_up",
            "premature_exit_validation": text(first(profit.get("premature_exit_status"), "insufficient_evidence")),
            "late_exit_validation": text(first(profit.get("late_exit_status"), learned.get("baseline_vs_learned_status"), "insufficient_evidence")),
            "profit_capture_blockers": blockers[:8] or [text(learned.get("baseline_vs_learned_status"), "profit_capture_persistence_window_incomplete")],
            "highest_roi_profit_capture_improvement": text(first(targeted.get("highest_roi_next_improvement"), profit.get("highest_roi_profit_capture_improvement"), "validate_profit_lock_and_catalyst_decay_windows_before_micro_test")),
            "paper_micro_test_consideration": "not_ready" if not ready else "human_review_candidate",
            "no_exit_behavior_changed": True,
        }

    def _regime_validation(self, statuses: dict[str, Any]) -> dict[str, Any]:
        market = status_value(statuses, "market_condition_attribution_v1")
        transition = status_value(statuses, "market_transition_detection_v1")
        confidence = rounded(first(market.get("condition_confidence_score"), transition.get("transition_confidence"), 0.0), 3)
        return {
            "status": "validating" if confidence >= 35 else "insufficient_evidence",
            "regime_confidence": confidence,
            "best_regime": market.get("best_condition"),
            "weakest_regime": market.get("weakest_condition"),
            "best_horizon_by_condition": market.get("best_horizon_by_condition") or {},
            "exit_quality_by_condition": market.get("exit_quality_by_condition") or {},
            "strategy_by_regime_answer": "condition_rows_available" if market.get("condition_rows") else "collect_more_regime_outcomes",
            "copilot_accuracy_impact": "moderate_positive_when_condition_confidence_improves" if confidence >= 50 else "limited_by_regime_confidence",
        }

    def _symbol_memory(self, statuses: dict[str, Any]) -> dict[str, Any]:
        family = status_value(statuses, "trade_family_intelligence_v1")
        shadow = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        evidence = max(to_int(family.get("evidence_count"), 0), to_int(shadow.get("candidate_decision_record_count"), 0))
        confidence = rounded(first(family.get("family_transfer_confidence"), shadow.get("shadow_alpha_confidence"), 0.0), 3)
        rows = _safe_list(family.get("family_rows"), 6)
        return {
            "status": "validating" if evidence >= 50 else "insufficient_evidence",
            "symbol_memory_confidence": confidence,
            "evidence_count": evidence,
            "best_understood_symbols_or_families": [row.get("trade_family") for row in rows if isinstance(row, dict)][:5],
            "strongest_trade_family": family.get("strongest_trade_family"),
            "weakest_trade_family": family.get("weakest_trade_family"),
            "best_horizon": family.get("best_family_horizon"),
            "best_exit_style": family.get("best_family_exit_style"),
            "does_symbol_memory_improve_decisions": "not_yet_proven" if confidence < 65 else "supportive_evidence_building",
            "symbols_needing_more_evidence": _safe_list(family.get("weakest_trade_family"), 3),
        }

    def _opportunity_cost(self, statuses: dict[str, Any]) -> dict[str, Any]:
        opp = status_value(statuses, "opportunity_cost_learning") or status_value(statuses, "opportunity_cost_learning_v1")
        ranking = status_value(statuses, "candidate_ranking_attribution_promotion_intelligence_v1")
        score = rounded(first(opp.get("opportunity_cost_score"), ranking.get("ranking_predictive_power"), 0.0), 3)
        return {
            "status": "validating" if ranking else "insufficient_evidence",
            "opportunity_cost_score": score,
            "missed_winners": first(opp.get("missed_winners"), ranking.get("missed_winners"), 0),
            "avoided_losers": first(opp.get("avoided_losers"), "warming_up"),
            "better_alternatives": first(opp.get("better_alternatives"), ranking.get("biggest_missed_promotion"), None),
            "worse_alternatives": first(opp.get("worse_alternatives"), ranking.get("biggest_false_promotion"), None),
            "opportunity_cost_by_horizon": opp.get("opportunity_cost_by_horizon") or {},
            "opportunity_cost_by_regime": opp.get("opportunity_cost_by_regime") or {},
            "opportunity_cost_by_ranking_factor": opp.get("opportunity_cost_by_ranking_factor") or {"dominant_blind_spot": ranking.get("dominant_ranking_blind_spot")},
            "why_astra_missed_it": text(first(ranking.get("dominant_ranking_mistake"), "ranking_attribution_gap_or_capacity_constraint")),
            "did_avoiding_trade_save_losses": "not_yet_proven",
        }

    def _learning_efficiency(self, statuses: dict[str, Any], optimization: dict[str, Any]) -> dict[str, Any]:
        compression = optimization.get("information_compression_summary") or {}
        evidence = status_value(statuses, "evidence_quality_scoring_v1")
        roi = status_value(statuses, "learning_roi_engine_v1")
        raw_count = to_int(first(evidence.get("raw_evidence_count"), roi.get("evidence_count"), status_value(statuses, "shadow_vs_paper_performance_attribution_v1").get("canonical_closed_trade_count"), 0), 0)
        quality = rounded(first(evidence.get("average_evidence_quality"), compression.get("memory_usefulness"), 0.0), 3)
        signal = rounded(first(compression.get("signal_to_noise_score"), quality, 0.0), 3)
        return {
            "status": "ok" if signal >= 50 else "needs_compression",
            "evidence_quality": text(first(evidence.get("quality_bucket"), compression.get("evidence_quality"), "warming_up")),
            "raw_evidence_count": raw_count,
            "weighted_evidence_count": rounded(first(evidence.get("weighted_evidence_count"), raw_count * quality / 100.0, 0.0), 3),
            "memory_usefulness": quality,
            "retrieval_usefulness": rounded(first(roi.get("retrieval_usefulness"), quality, 0.0), 3),
            "duplicate_information": to_int(compression.get("duplicate_observations"), 0),
            "stale_information": to_int(compression.get("stale_observations"), 0),
            "signal_to_noise_ratio": signal,
            "learning_roi": rounded(first(roi.get("learning_roi_score"), signal, 0.0), 3),
            "is_collecting_too_much": bool(compression.get("is_collecting_too_much")),
            "is_collecting_too_little": bool(compression.get("is_collecting_too_little")),
            "what_should_be_compressed": "duplicate_or_stale_diagnostics" if compression.get("is_collecting_too_much") else "large_append_only_state_after_preserving_truth",
            "what_should_be_expanded": "profit_capture_regime_and_symbol_persistence_evidence",
            "what_should_be_reduced": "low_value_duplicate_endpoint_scans",
        }

    def _shadow_promotion(self, statuses: dict[str, Any], optimization: dict[str, Any]) -> dict[str, Any]:
        shadow = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        learned = status_value(statuses, "controlled_paper_learned_exit_validation_v1")
        promotion = optimization.get("promotion_readiness_oversight") or {}
        readiness = rounded(first(promotion.get("promotion_readiness_score"), learned.get("policy_confidence"), shadow.get("shadow_alpha_confidence"), 0.0), 3)
        ready = bool(promotion.get("ready_for_paper_micro_test") and readiness >= 65)
        blockers = _safe_list(promotion.get("promotion_blockers"), 8) or _safe_list(learned.get("paper_exit_path_blockers"), 8)
        return {
            "status": "ready_for_paper_micro_test" if ready else "continue_collecting_evidence" if not blockers else "blocked",
            "shadow_vs_paper_performance": {
                "paper_profit_factor": shadow.get("paper_profit_factor_verified") or shadow.get("canonical_profit_factor"),
                "shadow_profit_factor": shadow.get("shadow_profit_factor_verified") or shadow.get("canonical_shadow_profit_factor"),
                "shadow_alpha_available": shadow.get("shadow_alpha_available"),
                "shadow_alpha_confidence": shadow.get("shadow_alpha_confidence"),
            },
            "shadow_persistence": text(first(shadow.get("shadow_persistence_status"), "insufficient_evidence")),
            "shadow_stability": text(first(shadow.get("shadow_stability_status"), "warming_up")),
            "promotion_readiness_score": readiness,
            "ready_for_paper_micro_test": ready,
            "continue_collecting_evidence": not ready,
            "blocked": bool(blockers),
            "rejected": False,
            "human_review_required": True,
            "blockers": blockers,
            "automatic_promotion_enabled": False,
        }

    def _copilot_accuracy(self, statuses: dict[str, Any], parts: dict[str, Any]) -> dict[str, Any]:
        weights = {
            "ranking_attribution": parts["ranking_attribution"].get("ranking_confidence", 0),
            "regime_intelligence": parts["regime_validation"].get("regime_confidence", 0),
            "symbol_memory": parts["symbol_memory"].get("symbol_memory_confidence", 0),
            "catalyst_intelligence": first(status_value(statuses, "catalyst_lifecycle_intelligence_v1").get("catalyst_lifecycle_confidence"), 0),
            "profit_capture": parts["profit_capture"].get("profit_capture_confidence", 0),
            "exit_intelligence": first(status_value(statuses, "controlled_paper_learned_exit_validation_v1").get("policy_confidence"), 0),
            "opportunity_cost": parts["opportunity_cost"].get("opportunity_cost_score", 0),
            "shadow_validation": parts["shadow_promotion"].get("promotion_readiness_score", 0),
            "truth_reconciliation": first(status_value(statuses, "shadow_vs_paper_performance_attribution_v1").get("truth_consistency_score"), 70),
        }
        numeric = {k: rounded(v, 3) for k, v in weights.items()}
        best = max(numeric, key=lambda k: numeric[k], default="ranking_attribution")
        worst = min(numeric, key=lambda k: numeric[k], default="profit_capture")
        score = rounded(sum(numeric.values()) / max(1, len(numeric)), 3)
        return {
            "status": "validating" if score >= 35 else "insufficient_evidence",
            "copilot_accuracy_attribution_score": score,
            "contribution_scores": numeric,
            "what_most_improves_copilot_accuracy": best,
            "what_most_hurts_copilot_accuracy": worst,
            "highest_roi_path_to_better_copilot_accuracy": "complete_profit_capture_and_regime_calibration" if worst in {"profit_capture", "regime_intelligence"} else "complete_ranking_attribution_and_shadow_validation",
        }

    def _recommendations(self, parts: dict[str, Any]) -> list[dict[str, Any]]:
        candidates = [
            {
                "recommendation": "complete_profit_capture_validation_before_paper_micro_tests",
                "expected_benefit": "improves exit quality, giveback reduction, and Copilot sell-review accuracy",
                "confidence": parts["profit_capture"].get("profit_capture_confidence", 0),
                "risk": "low_advisory_only",
                "effort": "medium",
                "dependency": "closed_trade_persistence_and_exit_path_truth",
                "validation_requirement": "profit_capture_confidence>=65 and blockers cleared",
                "roi_score": clamp(80 - to_float(parts["profit_capture"].get("profit_capture_confidence"), 0) * 0.35),
            },
            {
                "recommendation": "cache_or_fallback_slowest_unified_diagnostic_paths",
                "expected_benefit": "keeps dashboard and unified diagnostics practical while preserving intelligence",
                "confidence": 78,
                "risk": "low_no_behavior_change",
                "effort": "low_medium",
                "dependency": parts["performance_storage"].get("slowest_system"),
                "validation_requirement": "unified_diagnostics_returns_with_cached_heavy_sections",
                "roi_score": 74,
            },
            {
                "recommendation": "complete_ranking_attribution_for_missed_winners_and_horizon_bias",
                "expected_benefit": "improves candidate prioritization explanations and future tie-breaker validation",
                "confidence": parts["ranking_attribution"].get("ranking_confidence", 0),
                "risk": "low_shadow_only",
                "effort": "medium",
                "dependency": "candidate_decision_and_outcome_mapping",
                "validation_requirement": "ranking_attribution_score_and_predictive_power_improve_without_behavior_change",
                "roi_score": clamp(to_float(parts["ranking_attribution"].get("ranking_confidence", 0)) * 0.8 + 18),
            },
            {
                "recommendation": "increase_symbol_and_regime_persistence_evidence_quality",
                "expected_benefit": "improves Copilot accuracy and horizon/exit explanations by context",
                "confidence": min(to_float(parts["symbol_memory"].get("symbol_memory_confidence", 0)), to_float(parts["regime_validation"].get("regime_confidence", 0))),
                "risk": "low_cached_evidence_only",
                "effort": "medium",
                "dependency": "more completed lifecycle outcomes by symbol/regime",
                "validation_requirement": "symbol_memory_confidence>=65 and regime_confidence>=55",
                "roi_score": 62,
            },
            {
                "recommendation": "compress_large_state_after_preserving_canonical_truth",
                "expected_benefit": "reduces storage pressure and backup/runtime friction",
                "confidence": parts["performance_storage"].get("storage_pressure_score", 0),
                "risk": "medium_requires_preservation_plan_no_auto_delete",
                "effort": "medium",
                "dependency": parts["performance_storage"].get("largest_state_file", {}).get("name") if isinstance(parts["performance_storage"].get("largest_state_file"), dict) else "state_inventory",
                "validation_requirement": "archive_plan_proves_no_knowledge_loss_before_any_cleanup",
                "roi_score": clamp(to_float(parts["performance_storage"].get("storage_pressure_score", 0)) + 25),
            },
        ]
        candidates.sort(key=lambda row: to_float(row.get("roi_score"), 0.0), reverse=True)
        return candidates

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        optimization = status_value(statuses, "astra_autonomous_optimization_governance_core_v1")
        state = self._state_inventory()
        parts: dict[str, Any] = {}
        parts["performance_storage"] = self._performance_storage(statuses, optimization, state)
        parts["ranking_attribution"] = self._ranking_attribution(statuses)
        parts["profit_capture"] = self._profit_capture(statuses)
        parts["regime_validation"] = self._regime_validation(statuses)
        parts["symbol_memory"] = self._symbol_memory(statuses)
        parts["opportunity_cost"] = self._opportunity_cost(statuses)
        parts["learning_efficiency"] = self._learning_efficiency(statuses, optimization)
        parts["shadow_promotion"] = self._shadow_promotion(statuses, optimization)
        parts["copilot_accuracy"] = self._copilot_accuracy(statuses, parts)
        recommendations = self._recommendations(parts)
        top = recommendations[0] if recommendations else {}
        slowest = parts["performance_storage"].get("slowest_system")
        storage_issue = parts["performance_storage"].get("storage_issue")
        top_weaknesses = [
            parts["profit_capture"].get("highest_roi_profit_capture_improvement"),
            parts["ranking_attribution"].get("top_ranking_weaknesses", ["ranking_attribution_gap"])[0],
            parts["copilot_accuracy"].get("what_most_hurts_copilot_accuracy"),
            slowest,
            storage_issue,
        ]
        top_strengths = [
            parts["ranking_attribution"].get("top_ranking_strengths", ["ranking_evidence"])[0],
            parts["symbol_memory"].get("strongest_trade_family"),
            "paper_only_safety_controls",
            "dashboard_provider_calls_zero",
            "cache_first_attribution_completion",
        ]
        payload = {
            "enabled": True,
            "version": "1.0.0",
            "suite": "Astra Autonomous Improvement, Performance Optimization & Attribution Completion Suite V1",
            "status": "ok",
            "mode": self.mode,
            "generated_at": now_iso(),
            "autonomous_improvement_self_optimization_loop_v1": {
                "status": "active_advisory",
                "weaknesses_detected": [w for w in top_weaknesses if w][:8],
                "experiments_proposed": recommendations[:5],
                "corrections_implemented": _safe_list((optimization.get("improvement_attribution_summary") or {}).get("improvement_rows"), 8),
                "before_after_results": (optimization.get("improvement_attribution_summary") or {}).get("improvement_rows") or [],
                "success_failure_status": "evidence_backed_recommendations_generated",
                "confidence_score": rounded(parts["copilot_accuracy"].get("copilot_accuracy_attribution_score"), 3),
                "roi_score": rounded(top.get("roi_score"), 3),
                "next_action": top.get("recommendation"),
                "why": top.get("expected_benefit"),
                "dependency_block": top.get("dependency"),
                "success_proof_required": top.get("validation_requirement"),
            },
            "performance_storage_optimization_suite_v1": parts["performance_storage"],
            "ranking_attribution_completion_v1": parts["ranking_attribution"],
            "profit_capture_validation_completion_v1": parts["profit_capture"],
            "regime_intelligence_validation_calibration_v1": parts["regime_validation"],
            "symbol_intelligence_validation_behavioral_memory_v1": parts["symbol_memory"],
            "opportunity_cost_non_selection_intelligence_v1": parts["opportunity_cost"],
            "autonomous_knowledge_quality_learning_efficiency_v1": parts["learning_efficiency"],
            "shadow_promotion_readiness_intelligence_v1": parts["shadow_promotion"],
            "executive_improvement_prioritization_engine_v1": {
                "status": "ok",
                "best_next_improvement_one_codex_cycle": top,
                "best_next_three_improvements": recommendations[:3],
                "highest_roi_improvement": top.get("recommendation"),
                "lowest_risk_improvement": "cache_or_fallback_slowest_unified_diagnostic_paths",
                "highest_trading_impact_improvement": "complete_profit_capture_validation_before_paper_micro_tests",
                "highest_reliability_impact_improvement": "cache_or_fallback_slowest_unified_diagnostic_paths",
                "highest_copilot_accuracy_improvement": parts["copilot_accuracy"].get("highest_roi_path_to_better_copilot_accuracy"),
                "top_5_recommendations": recommendations[:5],
            },
            "autonomous_copilot_accuracy_attribution_v1": parts["copilot_accuracy"],
            "top_weaknesses": [w for w in top_weaknesses if w],
            "top_strengths": [s for s in top_strengths if s],
            "slowest_system": slowest,
            "storage_issue": storage_issue,
            "ranking_attribution_findings": parts["ranking_attribution"],
            "profit_capture_findings": parts["profit_capture"],
            "regime_findings": parts["regime_validation"],
            "symbol_memory_findings": parts["symbol_memory"],
            "opportunity_cost_findings": parts["opportunity_cost"],
            "learning_efficiency_findings": parts["learning_efficiency"],
            "copilot_accuracy_findings": parts["copilot_accuracy"],
            "highest_roi_next_improvement": top.get("recommendation"),
            "recommended_next_roadmap_item": "profit_capture_validation_cache_fallback_and_ranking_attribution_completion",
            "top_5_recommendations": recommendations[:5],
            "learning_center_summary": {
                "improvement_loop_status": "active_advisory",
                "slowest_system": slowest,
                "storage_pressure": parts["performance_storage"].get("storage_pressure_score"),
                "ranking_attribution_score": parts["ranking_attribution"].get("ranking_attribution_score"),
                "profit_capture_confidence": parts["profit_capture"].get("profit_capture_confidence"),
                "regime_validation_status": parts["regime_validation"].get("status"),
                "symbol_memory_status": parts["symbol_memory"].get("status"),
                "opportunity_cost_score": parts["opportunity_cost"].get("opportunity_cost_score"),
                "learning_efficiency_score": parts["learning_efficiency"].get("signal_to_noise_ratio"),
                "copilot_accuracy_attribution_score": parts["copilot_accuracy"].get("copilot_accuracy_attribution_score"),
                "highest_roi_next_improvement": top.get("recommendation"),
            },
            "safety_confirmations": _safety_flags(),
            **_safety_flags(),
        }
        return with_safety(payload)
