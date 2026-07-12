"""Build J bounded lifecycle-retention and active-learning contracts.

The module consumes existing broker, shadow, replay, warehouse, and librarian
summaries. It deliberately does not create a second lifecycle store, modify a
lesson, or make an execution decision.
"""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import (
    CachedDiagnosticModule,
    clamp,
    now_iso,
    rounded,
    status_value,
    to_float,
    to_int,
    with_safety,
)

VERSION = "1.0.0"
RETENTION_CLASSES = (
    "PERMANENT_AUTHORITATIVE",
    "PERMANENT_DURABLE_LESSON",
    "LONG_TERM_EXCEPTION",
    "WARM_EXPERIMENT_DETAIL",
    "COLD_COMPRESSED_DETAIL",
    "REBUILDABLE_TEMPORARY",
    "DUPLICATE_REMOVABLE",
    "EXPIRED_SAFE_TO_REMOVE",
)
SIMILARITY_DIMENSIONS = (
    "symbol_behavior", "regime", "horizon", "trade_style", "catalyst",
    "entry_setup", "exit_reason", "mfe_mae", "opportunity_cost", "return_per_day",
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _evidence_count(payload: dict[str, Any]) -> int:
    return max(
        to_int(payload.get("canonical_closed_trade_count"), 0),
        to_int(payload.get("completed_lifecycles"), 0),
        to_int(payload.get("tracked_lifecycles"), 0),
        to_int(payload.get("evidence_count"), 0),
    )


class ShadowLifecycleCompressionRetentionV1(CachedDiagnosticModule):
    module_name = "shadow_lifecycle_compression_retention_v1"
    mode = "shadow_only_lifecycle_compression_and_retention_diagnostics"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        broker = status_value(statuses, "broker_truth_accumulation_v2")
        shadow = status_value(statuses, "realistic_shadow_evidence_learning_lab_v1")
        replay = status_value(statuses, "replay_counterfactual_learning_v2")
        comparison = status_value(statuses, "shadow_vs_paper_performance_attribution_v1")
        warehouse = status_value(statuses, "astra_knowledge_warehouse_v1")
        broker_complete = to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0)
        shadow_complete = max(to_int(shadow.get("completed_lifecycles"), 0), to_int(comparison.get("shadow_completed_lifecycle_count"), 0))
        replay_count = max(to_int(replay.get("tracked_lifecycles"), 0), to_int(replay.get("counterfactuals_generated"), 0) // 14)
        twin_linked = min(broker_complete, shadow_complete, replay_count)
        checkpoint_policy = {
            "persisted_transitions": [
                "entry_decision", "entry_fill", "thesis_confirmation", "thesis_deterioration",
                "new_mfe", "new_mae", "momentum_state_change", "regime_state_change",
                "profit_protection_opportunity", "exit_readiness_transition",
                "replacement_candidate_emergence", "actual_exit", "shadow_exit", "final_comparison",
            ],
            "unchanged_hold_state_policy": "deduplicate_or_roll_up_into_compressed_interval",
            "combinatorial_experiment_cap": "existing_replay_counterfactual_governed_set",
            "hindsight_guard": "shadow_and_replay_evidence_never_reported_as_broker_truth",
        }
        retention = [
            {"retention_class": "PERMANENT_AUTHORITATIVE", "contents": ["broker_truth", "recommendation_order_fill_lineage", "final_paper_shadow_comparison"], "destructive_action_allowed": False},
            {"retention_class": "PERMANENT_DURABLE_LESSON", "contents": ["validated_lessons", "human_review_decisions", "contradictions"], "destructive_action_allowed": False},
            {"retention_class": "LONG_TERM_EXCEPTION", "contents": ["outliers", "rare_regimes", "execution_failures"], "destructive_action_allowed": False},
            {"retention_class": "WARM_EXPERIMENT_DETAIL", "contents": ["active_shadow_checkpoints"], "destructive_action_allowed": False},
            {"retention_class": "COLD_COMPRESSED_DETAIL", "contents": ["deduplicated_historical_checkpoints"], "destructive_action_allowed": False},
            {"retention_class": "REBUILDABLE_TEMPORARY", "contents": ["derived_cache_payloads"], "destructive_action_allowed": False},
            {"retention_class": "DUPLICATE_REMOVABLE", "contents": ["duplicate_derived_records"], "destructive_action_allowed": False},
            {"retention_class": "EXPIRED_SAFE_TO_REMOVE", "contents": ["expired_rebuildable_cache"], "destructive_action_allowed": False},
        ]
        status = "ok" if shadow_complete or broker_complete else "insufficient_evidence"
        return with_safety({
            "endpoint": "/api/shadow_lifecycle_compression_retention_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "canonical_owners": {"broker_truth": "broker_truth_records_v1", "shadow": "realistic_shadow_evidence_learning_lab_v1", "replay": "replay_counterfactual_learning_v2", "retrieval": "astra_knowledge_warehouse_v1"},
            "paper_shadow_twin": {
                "eligible_paper_lifecycles": broker_complete,
                "shadow_lifecycles": shadow_complete,
                "replay_lifecycles": replay_count,
                "linked_complete_twins": twin_linked,
                "linkage_status": "LINKED_AND_MEASURABLE" if twin_linked >= 5 else "FORWARD_LINKAGE_ACCUMULATING",
                "original_decision_timestamp_required": True,
                "information_available_at_timestamp_only": True,
            },
            "meaningful_checkpoint_policy": checkpoint_policy,
            "bounded_shadow_alternatives": ["skip", "delayed_entry", "confirmation_entry", "earlier_profit_protection", "momentum_deterioration_exit", "thesis_failure_exit", "longer_hold", "opportunity_cost_replacement"],
            "lifecycle_summary_contract": ["recommendation_id", "broker_lifecycle_id", "paper_baseline", "shadow_variant_ids", "entry_exit", "mfe", "mae", "hold_duration", "return_per_day", "comparison", "realism_score", "leakage_check", "lesson_ids", "retention_state"],
            "retention_classes": retention,
            "retention_class_names": list(RETENTION_CLASSES),
            "similarity_dimensions": list(SIMILARITY_DIMENSIONS),
            "representative_exception_protection": ["winners", "losers", "outliers", "rare_regimes", "contradictions", "execution_failures"],
            "storage_protection": {"warehouse_manager_required": True, "manifest_index_first": bool(warehouse.get("manifest_first") or warehouse.get("canonical_layer")), "checksum_reconciliation_required_before_mutation": True, "legacy_reader_compatibility_required": True, "destructive_migration_performed": False},
            "retention_state": "DIAGNOSTIC_POLICY_ONLY",
            "full_history_scans": 0,
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
        })


class ActiveLearningEvidenceGapV1(CachedDiagnosticModule):
    module_name = "active_learning_evidence_gap_v1"
    mode = "advisory_active_learning_gap_prioritization"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        broker = status_value(statuses, "broker_truth_accumulation_v2")
        lifecycle = status_value(statuses, "shadow_lifecycle_compression_retention_v1")
        effectiveness = status_value(statuses, "astra_intelligence_effectiveness_learning_velocity_v1")
        replay = status_value(statuses, "replay_counterfactual_learning_v2")
        crypto = status_value(statuses, "crypto_shadow_learning_v1")
        broker_sample = to_int(broker.get("total_complete_broker_confirmed_lifecycles"), 0)
        linked_twins = to_int((lifecycle.get("paper_shadow_twin") or {}).get("linked_complete_twins"), 0)
        crypto_sample = to_int(crypto.get("crypto_completed_lifecycles"), 0)
        specs = (
            ("completed_broker_truth", broker_sample, 50, 100.0, "natural_paper_lifecycle_accumulation"),
            ("paper_shadow_twin_linkage", linked_twins, 25, 90.0, "persist_forward_recommendation_and_fill_linkage"),
            ("exit_outcomes", broker_sample, 50, 88.0, "wait_for_broker_confirmed_natural_exits"),
            ("horizon_outcomes", linked_twins, 25, 82.0, "bounded_shadow_and_replay_comparison"),
            ("regime_diversity", _evidence_count(replay), 50, 72.0, "bounded_historical_replay"),
            ("opportunity_cost", _evidence_count(replay), 25, 70.0, "counterfactual_replacement_analysis"),
            ("crypto_separate_evidence", crypto_sample, 50, 50.0, "crypto_shadow_only_collection"),
            ("consumer_influence", to_int(effectiveness.get("decision_fields_influenced"), 0), 25, 95.0, "record_permitted_consumer_field_influence"),
        )
        gaps = []
        for name, current, desired, impact, path in specs:
            missing = max(0, desired - current)
            if missing:
                priority = clamp(impact * 0.65 + (missing / max(1, desired)) * 35.0)
                gaps.append({"gap": name, "current_sample": current, "desired_sample": desired, "missing_evidence": missing, "why_it_matters": "decision_truth_or_learning_effectiveness_is_not_yet measurable", "expected_decision_impact": rounded(impact), "safe_research_path": path, "blocked_reason": "natural_evidence_accumulation_required", "priority_score": rounded(priority)})
        gaps.sort(key=lambda row: -to_float(row.get("priority_score"), 0.0))
        negative_lessons = [{"lesson_type": "negative", "pattern": replay.get("most_common_missed_improvement") or "insufficient_evidence", "evidence_class": "REPLAY_COUNTERFACTUAL", "sample_maturity": "warming_up", "prohibited_use": "no_direct_execution_change"}]
        return with_safety({
            "endpoint": "/api/active_learning_evidence_gap_v1",
            "version": VERSION,
            "status": "ok" if gaps else "evidence_targets_met",
            "generated_at": now_iso(),
            "evidence_gaps": gaps,
            "active_learning_priority_queue": gaps[:10],
            "negative_lesson_intelligence": negative_lessons,
            "conflict_resolution_contract": {"teacher": "proposes_lesson", "challenger": "searches_for_leakage_contradiction_and_alternatives", "validator": "determines_state", "same_calculation_may_not_self_approve": True},
            "knowledge_decay_contract": {"decay_triggers": ["stale", "contradicted", "regime_mismatch", "symbol_behavior_change", "consumer_deterioration"], "revalidation_required": True},
            "consumer_teaching_contract": {"intended_consumers": ["Copilot", "Cortex", "Governance", "Learning", "entry_readiness", "exit_readiness", "opportunity_cost", "trade_style", "horizon", "symbol_memory", "shadow_experiments"], "prohibited_uses": ["direct_ranking_change", "direct_entry_change", "direct_exit_change", "broker_action"], "minimum_evidence_required": True},
            "evidence_class_separation": {"broker_truth": broker_sample, "shadow_twin": linked_twins, "replay": _evidence_count(replay), "crypto_shadow": crypto_sample},
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class TeachingEffectivenessV1(CachedDiagnosticModule):
    module_name = "teaching_effectiveness_v1"
    mode = "observational_lesson_consumer_effectiveness"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        effectiveness = status_value(statuses, "astra_intelligence_effectiveness_learning_velocity_v1")
        librarian = status_value(statuses, "astra_tier2a_librarian_executive_truth_layer_v1")
        gaps = status_value(statuses, "active_learning_evidence_gap_v1")
        available = to_int(effectiveness.get("evidence_available"), 0)
        indexed = to_int(effectiveness.get("evidence_indexed"), 0)
        retrieved = to_int(effectiveness.get("evidence_retrieved"), 0)
        consumed = to_int(effectiveness.get("evidence_consumed"), 0)
        influenced = to_int(effectiveness.get("decision_fields_influenced"), 0)
        lessons = max(to_int((effectiveness.get("lesson_state_counts") or {}).get("lessons"), 0), to_int(librarian.get("lessons_organized"), 0))
        proof = {
            "lesson_created": lessons,
            "indexed": indexed,
            "retrieved": retrieved,
            "delivered": retrieved,
            "read_by_consumer": consumed,
            "permitted_field_influenced": influenced,
            "recommendation_linked": 0,
            "outcome_observed": 0,
            "usefulness_evaluated": 0,
            "delivery_is_not_counted_as_influence": True,
        }
        usefulness = rounded(influenced * 100.0 / max(1, consumed)) if consumed else 0.0
        return with_safety({
            "endpoint": "/api/teaching_effectiveness_v1",
            "version": VERSION,
            "status": "ok" if available else "insufficient_evidence",
            "generated_at": now_iso(),
            "teaching_proof": proof,
            "lesson_effectiveness": {"retrieval_count": retrieved, "consumer_count": len([row for row in effectiveness.get("evidence_chain") or [] if row.get("consumed")]), "influence_count": influenced, "linked_outcomes": 0, "improved_outcomes": 0, "worsened_outcomes": 0, "neutral_outcomes": 0, "contradiction_count": to_int((effectiveness.get("lesson_state_counts") or {}).get("contradicted"), 0), "override_count": 0, "usefulness_score": usefulness, "retirement_candidate_status": "not_measurable_until_outcome_linkage"},
            "consumer_coverage": effectiveness.get("consumer_coverage") or {},
            "highest_priority_gap": (gaps.get("active_learning_priority_queue") or [{}])[0],
            "outcome_effectiveness_status": "INSUFFICIENT_BROKER_LINKAGE",
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class BuildJFinalValidationV1(CachedDiagnosticModule):
    module_name = "build_j_final_validation_v1"
    mode = "build_j_integrated_shadow_retention_and_teaching_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        lifecycle = status_value(statuses, "shadow_lifecycle_compression_retention_v1")
        gaps = status_value(statuses, "active_learning_evidence_gap_v1")
        teaching = status_value(statuses, "teaching_effectiveness_v1")
        checks = {
            "canonical_lifecycle_owners_named": bool(lifecycle.get("canonical_owners")),
            "checkpoint_deduplication_policy": bool(lifecycle.get("meaningful_checkpoint_policy")),
            "permanent_truth_protected": any(row.get("retention_class") == "PERMANENT_AUTHORITATIVE" and not row.get("destructive_action_allowed") for row in lifecycle.get("retention_classes") or []),
            "bounded_alternatives": len(lifecycle.get("bounded_shadow_alternatives") or []) > 0,
            "evidence_gap_queue_available": isinstance(gaps.get("active_learning_priority_queue"), list),
            "teacher_challenger_separated": bool(gaps.get("conflict_resolution_contract", {}).get("same_calculation_may_not_self_approve")),
            "delivery_not_influence": teaching.get("teaching_proof", {}).get("delivery_is_not_counted_as_influence") is True,
            "provider_calls_zero": all(to_int(_dict(statuses.get(key)).get("provider_calls_used"), 0) == 0 for key in ("shadow_lifecycle_compression_retention_v1", "active_learning_evidence_gap_v1", "teaching_effectiveness_v1")),
            "behavior_unchanged": all(_dict(statuses.get(key)).get("behavior_safe_to_apply") is False for key in ("shadow_lifecycle_compression_retention_v1", "active_learning_evidence_gap_v1", "teaching_effectiveness_v1")),
        }
        failed = [name for name, passed in checks.items() if not passed]
        twin_count = to_int((lifecycle.get("paper_shadow_twin") or {}).get("linked_complete_twins"), 0)
        deferred = []
        if twin_count < 25:
            deferred.append("paper_shadow_twin_sample_below_25")
        if not to_int((teaching.get("teaching_proof") or {}).get("outcome_observed"), 0):
            deferred.append("lesson_to_outcome_effectiveness_not_yet_measurable")
        status = "BUILD_J_BLOCKED" if failed else "BUILD_J_PASS_WITH_DEFERRED_EVIDENCE" if deferred else "BUILD_J_PASS"
        return with_safety({
            "endpoint": "/api/build_j_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks": checks,
            "checks_failed": failed,
            "deferred_evidence_limitations": deferred,
            "adversarial_rescan": {"status": "PASS" if not failed else "BLOCKED", "leakage_check": "required", "asset_class_separation": True, "destructive_retention_actions": 0},
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "runtime_files_excluded": True,
        })
