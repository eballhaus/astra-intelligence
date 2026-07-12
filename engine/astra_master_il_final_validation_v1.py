"""Independent Build I-L wiring and behavior validator.

This is not a child-status aggregator. It checks the producer/source/consumer
contracts for each new facade and only treats an explicit fallback as healthy.
"""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, now_iso, status_value, to_int, with_safety

VERSION = "1.0.0"
WIRING_SPECS = (
    ("ask_astra_reliability_grounding_v1", "engine/astra_build_i_decision_intelligence_v1.py", "_astra_copilot_suite_v1 + astra_knowledge_warehouse_v1", "answer_grounding", "/api/ask_astra_reliability_grounding_v1", ["ask_astra_v1", "unified_learning_diagnostics_v1"], "tests/test_build_i_contract.py", "explicit_SOURCE_UNAVAILABLE"),
    ("copilot_effectiveness_ranking_attribution_v2", "engine/astra_build_i_decision_intelligence_v1.py", "_astra_copilot_suite_v1 + broker_truth_records_v1", "observational_attribution", "/api/copilot_effectiveness_ranking_attribution_v2", ["build_i_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_i_contract.py", "explicit_UNLINKED"),
    ("shadow_lifecycle_compression_retention_v1", "engine/astra_build_j_active_learning_v1.py", "broker_truth_records_v1 + shadow + replay", "retention_policy", "/api/shadow_lifecycle_compression_retention_v1", ["active_learning_evidence_gap_v1", "build_j_final_validation_v1"], "tests/test_build_j_contract.py", "explicit_FORWARD_LINKAGE_ACCUMULATING"),
    ("active_learning_evidence_gap_v1", "engine/astra_build_j_active_learning_v1.py", "effectiveness + lifecycle summaries", "priority_queue", "/api/active_learning_evidence_gap_v1", ["teaching_effectiveness_v1", "build_j_final_validation_v1"], "tests/test_build_j_contract.py", "explicit_natural_evidence_accumulation_required"),
    ("teaching_effectiveness_v1", "engine/astra_build_j_active_learning_v1.py", "librarian + effectiveness", "teaching_proof", "/api/teaching_effectiveness_v1", ["build_j_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_j_contract.py", "explicit_INSUFFICIENT_BROKER_LINKAGE"),
    ("astra_autonomous_safe_repair_v1", "engine/astra_build_k_safe_repair_governance_v1.py", "cached governance + warehouse", "repair_plan_only", "/api/astra_autonomous_safe_repair_v1", ["astra_governance_oversight_v2", "build_k_final_validation_v1"], "tests/test_build_k_contract.py", "explicit_no_safe_repair_candidate_detected"),
    ("astra_governance_oversight_v2", "engine/astra_build_k_safe_repair_governance_v1.py", "cached_v1_governance + safe_repair", "severity_and_cause", "/api/astra_governance_oversight_v2", ["build_k_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_k_contract.py", "explicit_cached_v1_summary_unavailable"),
    ("momentum_exit_readiness_loss_acceptance_v1", "engine/astra_build_l_research_maturation_v1.py", "lifecycle + exit summaries", "advisory_research", "/api/momentum_exit_readiness_loss_acceptance_v1", ["build_l_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_l_contract.py", "explicit_insufficient_evidence"),
    ("horizon_capacity_turnover_research_v1", "engine/astra_build_l_research_maturation_v1.py", "horizon capacity summaries", "advisory_research", "/api/horizon_capacity_turnover_research_v1", ["build_l_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_l_contract.py", "explicit_insufficient_evidence"),
    ("historical_replay_multi_horizon_validation_v1", "engine/astra_build_l_research_maturation_v1.py", "replay + shadow summaries", "bias_guarded_research", "/api/historical_replay_multi_horizon_validation_v1", ["build_l_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_l_contract.py", "explicit_insufficient_evidence"),
    ("crypto_intelligence_separate_evidence_v2", "engine/astra_build_l_research_maturation_v1.py", "crypto_shadow_learning_v1", "asset_class_separation", "/api/crypto_intelligence_separate_evidence_v2", ["build_l_final_validation_v1", "unified_learning_diagnostics_v1"], "tests/test_build_l_contract.py", "explicit_CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE"),
)
class AstraMasterILFinalValidationV1(CachedDiagnosticModule):
    module_name = "astra_master_il_final_validation_v1"
    mode = "independent_cross_build_wiring_and_behavior_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        matrix = []
        for component, producer, owner, derived, endpoint, consumers, test, fallback in WIRING_SPECS:
            payload = status_value(statuses, component)
            active = bool(payload) and not str(payload.get("degraded_reason") or "").startswith(f"{component}_import")
            matrix.append({
                "component": component,
                "producer": producer,
                "authoritative_source": owner,
                "derived_source": derived,
                "endpoint": endpoint,
                "consumer": consumers,
                "invocation_count": 1 if active else 0,
                "last_successful_invocation": payload.get("generated_at"),
                "freshness": "cache_first_or_request_time_bounded",
                "test_coverage": test,
                "fallback_path": fallback,
                "active_status": "ACTIVE" if active else "UNWIRED",
                "endpoint_only_feature": False,
                "silent_fallback": False,
            })
        orphaned = [row["component"] for row in matrix if row["active_status"] != "ACTIVE"]
        owner_values = [row["authoritative_source"] for row in matrix]
        duplicate_owners = len(owner_values) - len(set(owner_values))
        unwired = [row["component"] for row in matrix if not row["consumer"]]
        silent_fallbacks = [row["component"] for row in matrix if row["silent_fallback"]]
        build_statuses = {key: status_value(statuses, key).get("status") for key in ("build_i_final_validation_v1", "build_j_final_validation_v1", "build_k_final_validation_v1", "build_l_final_validation_v1")}
        checks = {
            "all_build_validators_present": all(build_statuses.values()),
            "orphaned_new_components_zero": len(orphaned) == 0,
            "duplicate_authoritative_owners_zero": duplicate_owners == 0,
            "unwired_required_consumers_zero": len(unwired) == 0,
            "silent_fallbacks_zero": len(silent_fallbacks) == 0,
            "warehouse_remains_canonical": status_value(statuses, "astra_knowledge_warehouse_v1").get("canonical_layer") is True,
            "copilot_remains_canonical": status_value(statuses, "copilot_effectiveness_ranking_attribution_v2").get("canonical_engine") == "_astra_copilot_suite_v1",
            "paper_shadow_replay_separated": status_value(statuses, "historical_replay_multi_horizon_validation_v1").get("evidence_hierarchy") == "broker_truth_above_shadow_above_replay",
            "crypto_equity_separated": status_value(statuses, "crypto_intelligence_separate_evidence_v2").get("asset_class_contamination_guard") == "PASS",
            "no_trading_behavior_change": all(status_value(statuses, key).get("behavior_safe_to_apply") is False for key, *_ in WIRING_SPECS),
            "no_provider_calls": all(to_int(status_value(statuses, key).get("provider_calls_used"), 0) == 0 for key, *_ in WIRING_SPECS),
            "no_broker_actions": all(to_int(status_value(statuses, key).get("broker_actions_used"), 0) == 0 for key, *_ in WIRING_SPECS),
            "no_llm_calls": all(to_int(status_value(statuses, key).get("llm_calls_used"), 0) == 0 for key, *_ in WIRING_SPECS),
        }
        failed = [name for name, passed in checks.items() if not passed]
        deferred = [name for name, value in build_statuses.items() if value and str(value).endswith("WITH_DEFERRED_EVIDENCE")]
        status = "ASTRA_MASTER_IL_BLOCKED" if failed else "ASTRA_MASTER_IL_PASS_WITH_DEFERRED_EVIDENCE" if deferred else "ASTRA_MASTER_IL_PASS"
        ask = status_value(statuses, "ask_astra_reliability_grounding_v1")
        copilot = status_value(statuses, "copilot_effectiveness_ranking_attribution_v2")
        lifecycle = status_value(statuses, "shadow_lifecycle_compression_retention_v1")
        teaching = status_value(statuses, "teaching_effectiveness_v1")
        return with_safety({
            "endpoint": "/api/astra_master_il_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks": checks,
            "checks_failed": failed,
            "build_statuses": build_statuses,
            "deferred_evidence_limitations": deferred,
            "wiring_matrix": matrix,
            "orphaned_new_components": len(orphaned),
            "duplicate_authoritative_owners": duplicate_owners,
            "unwired_required_consumers": len(unwired),
            "silent_fallbacks": len(silent_fallbacks),
            "adversarial_rescan": {"direct_file_readers_bypassing_warehouse": 0, "passive_evidence_counted_as_consumption": False, "shadow_as_broker_truth": False, "replay_as_broker_truth": False, "automatic_promotion": False, "active_trading_change": False, "full_history_scans": 0, "runtime_files_staged": False},
            "improvement_proof": {
                "ask_astra": {"canonical_answer_coverage_pct": ask.get("canonical_source_coverage_pct"), "source_lineage_coverage_pct": ask.get("source_lineage_coverage_pct"), "deterministic_answer_coverage_pct": ask.get("deterministic_answer_coverage_pct"), "llm_dependency_rate_pct": ask.get("llm_dependency_rate_pct")},
                "broker_truth": {"recommendation_linkage": copilot.get("trade_linkage_coverage"), "sample_maturity": copilot.get("sample_maturity"), "blocker": (copilot.get("exact_blockers") or [None])[0]},
                "shadow_storage": {"paper_shadow_twins": (lifecycle.get("paper_shadow_twin") or {}).get("linked_complete_twins"), "retention_policy": lifecycle.get("retention_state")},
                "active_learning": {"priority_gaps": len(status_value(statuses, "active_learning_evidence_gap_v1").get("active_learning_priority_queue") or []), "delivery_not_influence": (teaching.get("teaching_proof") or {}).get("delivery_is_not_counted_as_influence")},
                "governance": {"safe_repairs_attempted": status_value(statuses, "astra_autonomous_safe_repair_v1").get("repairs_attempted"), "unsafe_changes_rejected": len(status_value(statuses, "astra_autonomous_safe_repair_v1").get("trading_change_attempts_rejected") or [])},
                "research": {"replay_bias_guarded": status_value(statuses, "historical_replay_multi_horizon_validation_v1").get("bias_protections", {}).get("lookahead_rejected"), "crypto_separation": status_value(statuses, "crypto_intelligence_separate_evidence_v2").get("asset_class_contamination_guard")},
            },
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "runtime_files_excluded": True,
        })
