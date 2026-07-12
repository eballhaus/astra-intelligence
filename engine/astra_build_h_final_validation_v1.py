"""Final Build H validation over existing and newly consolidated diagnostics."""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, now_iso, to_float, to_int, with_safety

VERSION = "1.0.0"


def _dict(statuses: dict[str, Any], key: str) -> dict[str, Any]:
    value = statuses.get(key)
    return dict(value) if isinstance(value, dict) else {}


class AstraBuildHFinalValidationV1(CachedDiagnosticModule):
    module_name = "astra_build_h_final_validation_v1"
    mode = "shadow_only_build_h_integrated_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        ownership = _dict(statuses, "astra_build_h_ownership_map_v1")
        warehouse = _dict(statuses, "astra_knowledge_warehouse_v1")
        effectiveness = _dict(statuses, "astra_intelligence_effectiveness_learning_velocity_v1")
        shadow = _dict(statuses, "astra_shadow_experiment_governance_v1")
        checks = {
            "ownership_map_available": ownership.get("status") in {"OWNERSHIP_MAP_PASS", "OWNERSHIP_MAP_PASS_WITH_WARNINGS"},
            "canonical_owner_assigned": to_int(ownership.get("canonical_owners_assigned"), 0) > 0,
            "warehouse_source_catalog_healthy": warehouse.get("canonical_layer") is True and warehouse.get("source_lineage_supported") is True,
            "bounded_reads_enforced": bool((warehouse.get("bounded_read_policy") or {}).get("max_results")) and warehouse.get("full_history_fallback") is False,
            "manifest_or_index_first": warehouse.get("manifest_first") is True,
            "effectiveness_chain_measurable": effectiveness.get("passive_presence_excluded") is True,
            "consumer_coverage_reported": isinstance(effectiveness.get("consumer_coverage"), dict),
            "shadow_contract_available": isinstance(shadow.get("experiment_contract_schema"), list),
            "exact_paper_baseline_required": shadow.get("exact_paper_baseline_required") is True,
            "automatic_promotion_disabled": shadow.get("automatic_promotions_enabled") is False,
            "provider_calls_zero": all(to_int(_dict(statuses, key).get("provider_calls_used"), 0) == 0 for key in ("astra_knowledge_warehouse_v1", "astra_intelligence_effectiveness_learning_velocity_v1", "astra_shadow_experiment_governance_v1")),
            "llm_calls_zero": all(to_int(_dict(statuses, key).get("llm_calls_used"), 0) == 0 for key in ("astra_knowledge_warehouse_v1", "astra_intelligence_effectiveness_learning_velocity_v1", "astra_shadow_experiment_governance_v1")),
            "behavior_safe_false": all(_dict(statuses, key).get("behavior_safe_to_apply") is False for key in ("astra_build_h_ownership_map_v1", "astra_knowledge_warehouse_v1", "astra_intelligence_effectiveness_learning_velocity_v1", "astra_shadow_experiment_governance_v1")),
            "paper_only_preserved": all(_dict(statuses, key).get("paper_only_preserved") is not False for key in ("astra_build_h_ownership_map_v1", "astra_knowledge_warehouse_v1", "astra_intelligence_effectiveness_learning_velocity_v1", "astra_shadow_experiment_governance_v1")),
            "equity_crypto_separation": shadow.get("equity_crypto_separation") is True,
            "replay_not_paper_truth": shadow.get("replay_is_not_paper_truth") is True,
        }
        failed = [key for key, value in checks.items() if not value]
        broker_truth = max(
            to_int(_dict(statuses, "shadow_vs_paper_performance_attribution_v1").get("canonical_closed_trade_count"), 0),
            to_int(_dict(statuses, "shadow_vs_paper_performance_attribution_v1").get("paper_trade_count"), 0),
        )
        shadow_sample = to_int(shadow.get("shadow_lifecycles"), 0)
        deferred = []
        if broker_truth < 50:
            deferred.append("broker_truth_sample_below_50_for_full_effectiveness_confirmation")
        if shadow_sample < 20:
            deferred.append("shadow_completed_lifecycle_sample_below_20_for_repeatability")
        if effectiveness.get("evidence_consumption_ratio") is None:
            deferred.append("explicit_consumption_ratio_not_proven_for_all_evidence_classes")
        status = "BUILD_H_BLOCKED" if failed else "BUILD_H_PASS_WITH_DEFERRED_EVIDENCE" if deferred else "BUILD_H_PASS"
        return with_safety({
            "endpoint": "/api/build_h_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks_passed": [key for key, value in checks.items() if value],
            "checks_failed": failed,
            "deferred_evidence": deferred,
            "critical_contradictions": 0,
            "broker_truth_sample": broker_truth,
            "shadow_completed_lifecycle_sample": shadow_sample,
            "evidence_consumption_ratio": effectiveness.get("evidence_consumption_ratio"),
            "influence_trace_coverage_pct": effectiveness.get("influence_trace_coverage_pct"),
            "automatic_promotions_enabled": False,
            "learned_exits_enabled": False,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
            "ranking_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "position_sizing_changed": False,
            "portfolio_allocation_changed": False,
            "capacity_changed": False,
            "runtime_files_excluded": True,
            "api_calls_used": 0,
            "provider_calls_used": 0,
            "llm_calls_used": 0,
        })
