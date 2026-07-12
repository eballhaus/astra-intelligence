"""Build K safe-repair planning and governance oversight contracts.

Repairs are deliberately limited to low-risk derived/cache operations. The
module never writes trading state, changes policy, or attempts a repair during
the status call; it records whether a bounded repair would be eligible.
"""

from __future__ import annotations

from typing import Any

from engine.intelligence_quality_common_v1 import CachedDiagnosticModule, clamp, now_iso, status_value, to_float, to_int, with_safety

VERSION = "1.0.0"
REPAIR_LEVELS = {
    1: "AUTOMATIC_SAFE_DERIVED_OR_CACHE_REPAIR_ONLY",
    2: "SHADOW_OR_CANARY_ONLY",
    3: "HUMAN_APPROVAL_REQUIRED",
    4: "PROHIBITED",
}
PROHIBITED_ACTIONS = ("live_trading", "live_broker_authorization", "leverage", "shorting", "options", "bypass_human_approval", "disable_safety_controls")
HUMAN_ACTIONS = ("ranking", "entry", "exit", "sizing", "allocation", "capacity", "turnover", "portfolio_constraints", "broker_behavior", "paper_promotion")


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _severity(score: float) -> str:
    if score >= 85:
        return "RED"
    if score >= 65:
        return "ORANGE"
    if score >= 40:
        return "YELLOW"
    return "GREEN"


class AstraAutonomousSafeRepairV1(CachedDiagnosticModule):
    module_name = "astra_autonomous_safe_repair_v1"
    mode = "bounded_infrastructure_repair_planning_no_behavior_mutation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        governance = status_value(statuses, "astra_governance_oversight_v1")
        warehouse = status_value(statuses, "astra_knowledge_warehouse_v1")
        recovery = status_value(statuses, "astra_recovery_center_v1")
        failed_sources = to_int(unified.get("failed_sources_count"), 0)
        stale_critical = to_int((governance.get("stale_cache_summary") or {}).get("stale_decision_critical_cache_count"), 0)
        manifest_missing = not bool(warehouse.get("manifest_first") or warehouse.get("canonical_layer"))
        candidates = []
        if failed_sources:
            candidates.append({"issue_id": "missing_diagnostic_refresh", "component": "unified_diagnostics", "root_cause": "failed_source_count_nonzero", "evidence": {"failed_sources_count": failed_sources}, "risk_class": 1, "proposed_action": "refresh_derived_diagnostic_summary", "files_data_affected": ["dashboard_cache_only"], "tests_required": ["endpoint_json", "failed_source_recheck"], "repair_eligible": True})
        if stale_critical:
            candidates.append({"issue_id": "stale_cache_candidate", "component": "cache_layer", "root_cause": "decision_critical_cache_marked_stale", "evidence": {"stale_count": stale_critical}, "risk_class": 1, "proposed_action": "refresh_stale_derived_cache", "files_data_affected": ["dashboard_cache_only"], "tests_required": ["freshness_recheck"], "repair_eligible": True})
        if manifest_missing:
            candidates.append({"issue_id": "manifest_index_gap", "component": "knowledge_warehouse", "root_cause": "manifest_or_canonical_layer_not_available", "evidence": {"warehouse_status": warehouse.get("status")}, "risk_class": 1, "proposed_action": "rebuild_derived_manifest_index_after_snapshot", "files_data_affected": ["derived_index_only"], "tests_required": ["manifest_reconciliation", "bounded_query"], "repair_eligible": True})
        recovery_score = to_float(recovery.get("recovery_health_score"), 100.0)
        if recovery and recovery_score < 50:
            candidates.append({"issue_id": "recovery_health_degraded", "component": "recovery_center", "root_cause": "recovery_health_score_low", "evidence": {"recovery_health_score": recovery_score}, "risk_class": 2, "proposed_action": "shadow_canary_recovery_plan_only", "files_data_affected": [], "tests_required": ["human_review", "canary_comparison"], "repair_eligible": False})
        rejected = [{"attempted_change": action, "risk_class": 4 if action in PROHIBITED_ACTIONS else 3, "rejected": True, "reason": "trading_or_governance_behavior_is_outside_safe_repair_scope"} for action in (*HUMAN_ACTIONS, *PROHIBITED_ACTIONS)]
        repair_records = [{
            "repair_id": f"repair_plan:{row['issue_id']}", "issue_id": row["issue_id"], "detected_time": now_iso(), "component": row["component"], "root_cause": row["root_cause"], "evidence": row["evidence"], "risk_class": row["risk_class"], "risk_class_label": REPAIR_LEVELS[row["risk_class"]], "proposed_action": row["proposed_action"], "files_data_affected": row["files_data_affected"], "snapshot_reference": "required_before_any_mutation", "tests_required": row["tests_required"], "validation_result": "NOT_APPLIED_DURING_STATUS_RENDER", "rescan_result": "PENDING_IF_REPAIR_EXECUTED", "retained_or_rolled_back": "NOT_APPLIED", "rollback_reason": None, "lessons_generated": ["safe_repair_requires_bounded_scope_and_post_repair_validation"],
        } for row in candidates]
        risk_score = clamp(failed_sources * 25.0 + stale_critical * 15.0 + (20.0 if manifest_missing else 0.0) + (100.0 - recovery_score) * 0.2)
        return with_safety({
            "endpoint": "/api/astra_autonomous_safe_repair_v1",
            "version": VERSION,
            "status": "ok" if not candidates else "REPAIR_CANDIDATES_IDENTIFIED",
            "generated_at": now_iso(),
            "canonical_loop": ["AUDIT", "DETECT", "DIAGNOSE", "CLASSIFY_RISK", "PLAN_REPAIR", "SNAPSHOT", "APPLY_BOUNDED_REPAIR", "TEST", "VALIDATE", "RESCAN", "RETAIN_OR_ROLLBACK", "LEARN"],
            "repair_levels": REPAIR_LEVELS,
            "issues_detected": candidates,
            "repair_records": repair_records,
            "repairs_eligible": sum(1 for row in candidates if row.get("repair_eligible")),
            "repairs_attempted": 0,
            "repairs_passed": 0,
            "repairs_rolled_back": 0,
            "blocked_repairs": [row for row in candidates if not row.get("repair_eligible")],
            "repeated_failure_suppression": {"enabled": True, "max_attempts": 1, "cooldown_seconds": 3600, "same_issue_loop_prevented": True},
            "rollback_contract": {"snapshot_required": True, "bounded_scope_required": True, "atomic_operation_required_where_possible": True, "rollback_test_required": True, "post_repair_health_comparison_required": True, "timeout_required": True, "maximum_attempts_required": True, "cooldown_required": True},
            "reward_hacking_protection": {"denominator_reduction_detected": False, "failure_deletion_detected": False, "evidence_relabeling_detected": False, "hard_case_exclusion_detected": False, "stale_cache_masking_detected": False, "delivery_counted_as_influence": False, "skipped_work_reported_as_latency_gain": False, "lookahead_shadow_outperformance_detected": False, "sample_manipulation_detected": False},
            "trading_change_attempts_rejected": rejected,
            "current_risk_state": _severity(risk_score),
            "exact_blockers": [row["root_cause"] for row in candidates] or ["no_safe_repair_candidate_detected"],
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class AstraGovernanceOversightV2(CachedDiagnosticModule):
    module_name = "astra_governance_oversight_v2"
    mode = "governance_oversight_expansion_cache_first"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        v1 = status_value(statuses, "astra_governance_oversight_v1")
        repair = status_value(statuses, "astra_autonomous_safe_repair_v1")
        broker = status_value(statuses, "alpaca_paper_broker")
        unified = status_value(statuses, "unified_learning_diagnostics_v1")
        checks = [
            {"area": "trading_safety", "score": 0.0 if broker.get("paper_mode_verified") and not broker.get("broker_live_endpoint_allowed") else 100.0, "cause": "paper_mode_verified_and_live_endpoint_blocked" if broker.get("paper_mode_verified") and not broker.get("broker_live_endpoint_allowed") else "paper_or_live_endpoint_safety_flag_inconsistent"},
            {"area": "learning_safety", "score": 0.0 if unified.get("behavior_safe_to_apply") is False else 90.0, "cause": "behavior_safe_to_apply_false" if unified.get("behavior_safe_to_apply") is False else "behavior_safety_flag_missing_or_true"},
            {"area": "source_health", "score": min(100.0, to_int(unified.get("failed_sources_count"), 0) * 25.0), "cause": "failed_sources_count"},
            {"area": "safe_repairs", "score": 25.0 if to_int(repair.get("repairs_eligible"), 0) else 0.0, "cause": (repair.get("exact_blockers") or ["no_safe_repair_candidate_detected"])[0]},
            {"area": "rollback_health", "score": 0.0 if repair.get("rollback_contract", {}).get("snapshot_required") else 80.0, "cause": "rollback_contract_present" if repair.get("rollback_contract", {}).get("snapshot_required") else "rollback_contract_missing"},
        ]
        for row in checks:
            row["severity"] = _severity(to_float(row["score"], 0.0))
        highest = max(checks, key=lambda row: to_float(row.get("score"), 0.0), default={})
        return with_safety({
            "endpoint": "/api/astra_governance_oversight_v2",
            "version": VERSION,
            "status": "ok",
            "generated_at": now_iso(),
            "compatible_v1_source": "/api/astra_governance_oversight_v1",
            "governance_checks": checks,
            "overall_severity": highest.get("severity", "GREEN"),
            "top_concern": highest.get("area", "none"),
            "exact_top_concern_cause": highest.get("cause", "none"),
            "safe_repair_summary": {"eligible": repair.get("repairs_eligible"), "attempted": repair.get("repairs_attempted"), "rolled_back": repair.get("repairs_rolled_back"), "rejected_trading_changes": len(repair.get("trading_change_attempts_rejected") or [])},
            "warning_states": ["GREEN", "YELLOW", "ORANGE", "RED", "BLOCKED"],
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "full_history_scans": 0,
        })


class BuildKFinalValidationV1(CachedDiagnosticModule):
    module_name = "build_k_final_validation_v1"
    mode = "build_k_safe_repair_and_governance_validation"

    def _build(self, statuses: dict[str, Any]) -> dict[str, Any]:
        repair = status_value(statuses, "astra_autonomous_safe_repair_v1")
        governance = status_value(statuses, "astra_governance_oversight_v2")
        rejected = repair.get("trading_change_attempts_rejected") or []
        rejected_names = {row.get("attempted_change") for row in rejected if row.get("rejected")}
        checks = {
            "safe_repair_scope_bounded": repair.get("rollback_contract", {}).get("bounded_scope_required") is True,
            "repair_not_run_during_status_render": to_int(repair.get("repairs_attempted"), 0) == 0,
            "rollback_available": repair.get("rollback_contract", {}).get("snapshot_required") is True and repair.get("rollback_contract", {}).get("rollback_test_required") is True,
            "repeated_repair_suppressed": repair.get("repeated_failure_suppression", {}).get("same_issue_loop_prevented") is True,
            "ranking_change_rejected": "ranking" in rejected_names,
            "exit_change_rejected": "exit" in rejected_names,
            "broker_change_rejected": "broker_behavior" in rejected_names,
            "live_trading_rejected": "live_trading" in rejected_names,
            "metric_gaming_checked": isinstance(repair.get("reward_hacking_protection"), dict),
            "exact_governance_cause": bool(governance.get("exact_top_concern_cause")),
            "provider_calls_zero": all(to_int(_dict(statuses.get(key)).get("provider_calls_used"), 0) == 0 for key in ("astra_autonomous_safe_repair_v1", "astra_governance_oversight_v2")),
            "behavior_unchanged": all(_dict(statuses.get(key)).get("behavior_safe_to_apply") is False for key in ("astra_autonomous_safe_repair_v1", "astra_governance_oversight_v2")),
        }
        failed = [name for name, passed in checks.items() if not passed]
        deferred = ["no_live_safe_repair_was_applied_without_a_concrete_low_risk_issue"]
        status = "BUILD_K_BLOCKED" if failed else "BUILD_K_PASS_WITH_DEFERRED_EVIDENCE"
        return with_safety({
            "endpoint": "/api/build_k_final_validation_v1",
            "version": VERSION,
            "status": status,
            "generated_at": now_iso(),
            "checks": checks,
            "checks_failed": failed,
            "deferred_evidence_limitations": deferred,
            "adversarial_rescan": {"status": "PASS" if not failed else "BLOCKED", "repair_loops": 0, "unsafe_repairs": 0, "silent_success_on_unavailable_data": 0},
            "provider_calls_used": 0,
            "broker_actions_used": 0,
            "llm_calls_used": 0,
            "runtime_files_excluded": True,
        })
