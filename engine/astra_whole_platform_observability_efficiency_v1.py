"""Bounded whole-platform fact adapter for Sentinel, Governance, and Cortex.

This module is deliberately not another monitor.  It converts the compact
status snapshots already produced by Astra's specialized owners into one
read-only control-plane packet.  Callers supply those snapshots; this module
does not read state, start workers, or call providers/brokers.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


VERSION = "1.0.0"
STALE_SECONDS = 30 * 60
SAFETY = {
    "get_route_read_only": True,
    "state_mutations_from_get": 0,
    "provider_calls_added": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
    "execution_behavior_changed": False,
    "ranking_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "sizing_behavior_changed": False,
    "allocation_behavior_changed": False,
    "capacity_behavior_changed": False,
    "frozen_lifecycle_modified": False,
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
}

# Each entry names the existing source-of-truth owner.  A missing source stays
# visible as a gap instead of being silently inferred by this adapter.
DOMAIN_SPECS = (
    ("backend", "Backend health contract", ("astra_operating_health_contract_v1", "health")),
    ("paper_autopilot_worker", "PaperAutopilot worker", ("paper_autopilot_status", "paper_autopilot_throughput")),
    ("frontend", "Dashboard data wiring", ("dashboard_data_wiring_v1",)),
    ("candidate_trading_pipeline", "Candidate decision ledger", ("candidate_lineage_governance_v2", "paper_execution_trace")),
    ("lane_capacity", "Canonical lane capacity", ("astra_learning_preservation_capacity_v1", "astra_broker_truth_throughput_v1")),
    ("broker", "Broker truth", ("alpaca_paper_status_v1", "astra_broker_truth_throughput_v1")),
    ("reconciliation", "Broker reconciliation", ("astra_trade_state_reconciliation_v1", "astra_broker_truth_all_in_one_audit_v1")),
    ("strict_truth", "Canonical lifecycle truth", ("cortex_lifecycle_evidence_master_truth_v1", "astra_post_reset_truth_v1")),
    ("learning", "Unified learning diagnostics", ("astra_evidence_consumption_teacher_shadow_v1", "astra_trading_intelligence_improvement_suite_v6")),
    ("historical_mining", "Historical Evidence Mining V8", ("astra_historical_evidence_mining_knowledge_distillation_v1",)),
    ("v10_runner", "Incremental Historical Learning Governor V10", ("astra_incremental_historical_learning_governor_v1",)),
    ("warehouse", "AstraKnowledgeWarehouseV1", ("astra_knowledge_warehouse_v1",)),
    ("retrieval_indexing", "Knowledge retrieval/indexing", ("knowledge_retrieval_indexing_v1", "long_term_memory_symbol_retrieval_suite_v1")),
    ("compression", "Knowledge Compression Engine V1", ("astra_evidence_consumption_teacher_shadow_v1",)),
    ("teacher", "Teacher Layer V1", ("astra_evidence_consumption_teacher_shadow_v1",)),
    ("satellites_helpers", "Satellite Coordinator", ("astra_tier3_historical_satellite_shadow_acceleration_v1", "astra_satellite_network_v1")),
    ("storage", "Storage/cache attribution", ("astra_storage_cache_attribution_learning_efficiency_v1",)),
    ("memory_resources", "Runtime resource governor", ("astra_runtime_resource_governance_v1",)),
    ("api_providers", "Provider orchestration", ("astra_provider_orchestration_data_governance_v1",)),
    ("autonomous_adaptation", "V7 / Cortex / Governance", ("astra_autonomous_learning_safe_adaptation_v1",)),
    ("sentinel", "Astra Sentinel", ("astra_sentinel_integrity_v1",)),
    ("governance", "Continuous Governance", ("astra_continuous_governance_v1", "astra_governance_coverage_consolidation_v1")),
    ("cortex", "Cortex master truth", ("cortex_lifecycle_evidence_master_truth_v1", "astra_cortex_paper_completion_status_v1")),
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any, default: str = "UNKNOWN") -> str:
    value = str(value or "").strip()
    return value.upper() if value else default


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp_age_seconds(source: Mapping[str, Any], now: datetime) -> float | None:
    for key in ("generated_at", "updated_at", "last_updated", "snapshot_at", "timestamp"):
        value = source.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return max(0.0, (now - parsed.astimezone(timezone.utc)).total_seconds())
        except ValueError:
            continue
    value = _number(source.get("snapshot_age_seconds") or source.get("age_seconds"))
    return value if value is not None and value >= 0 else None


def _source_for(statuses: Mapping[str, Any], keys: tuple[str, ...]) -> tuple[str | None, dict[str, Any]]:
    for key in keys:
        source = _mapping(statuses.get(key))
        if source:
            return key, source
    return None, {}


def _health(source: Mapping[str, Any]) -> str:
    status = _text(source.get("status") or source.get("current_status") or source.get("health") or source.get("governance_status"))
    if any(token in status for token in ("FAIL", "ERROR", "UNAVAILABLE", "CRITICAL")):
        return "FAIL"
    if any(token in status for token in ("WARNING", "DEGRADED", "BLOCKED", "DEFERRED", "STALE")):
        return "DEGRADED"
    if status.startswith("PASS") or status in {"OK", "READY", "HEALTHY", "OBSERVATIONAL_READY", "SHADOW_PRACTICE", "IDLE_OR_COMPLETE", "UNCHANGED"}:
        return "HEALTHY"
    if status in {"INSUFFICIENT_EVIDENCE", "WARMING_UP", "UNKNOWN"}:
        return "WARMING_UP" if status != "UNKNOWN" else "UNKNOWN"
    return status


def _blocker(source: Mapping[str, Any]) -> str:
    for key in ("first_causal_blocker", "exact_first_causal_blocker", "degraded_reason", "first_blocker", "blocker", "reason", "current_blocker"):
        value = source.get(key)
        if isinstance(value, str) and value.strip():
            return value
    blockers = source.get("blockers") or source.get("remaining_blockers") or source.get("activation_blockers")
    if isinstance(blockers, list) and blockers:
        return str(blockers[0])
    return "NONE_OBSERVED"


def _efficiency(source: Mapping[str, Any]) -> str:
    decision = _text((source.get("resource_decision") or {}).get("decision") if isinstance(source.get("resource_decision"), Mapping) else source.get("throughput_mode") or source.get("cache_status"))
    if "DEFER" in decision or "PRESSURE" in decision:
        return "RESOURCE_CONSTRAINED"
    if any(_number(source.get(key)) not in (None, 0.0) for key in ("full_history_scan_count", "provider_calls_used", "provider_calls_added")):
        return "REVIEW_USAGE"
    return "CACHE_FIRST_OR_UNKNOWN"


def _domain_rows(statuses: Mapping[str, Any], now: datetime) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for domain, owner, keys in DOMAIN_SPECS:
        source_key, source = _source_for(statuses, keys)
        if not source:
            rows.append({"domain": domain, "canonical_owner": owner, "monitored": "NO", "sentinel_visibility": "NOT_MONITORED", "governance_visibility": "NOT_MONITORED", "cortex_visibility": "NOT_MONITORED", "health": "UNKNOWN", "freshness": "UNKNOWN", "efficiency_state": "UNKNOWN", "first_causal_blocker": "NOT_MONITORED", "evidence_source": None})
            continue
        age = _timestamp_age_seconds(source, now)
        stale = age is not None and age > STALE_SECONDS
        freshness = "STALE" if stale else "CURRENT" if age is not None else "UNSPECIFIED"
        source_health = _health(source)
        if stale and source_health == "HEALTHY":
            source_health = "STALE_HEALTH_UNVERIFIED"
        rows.append({"domain": domain, "canonical_owner": owner, "monitored": "YES", "sentinel_visibility": "VISIBLE" if domain != "sentinel" else "SELF_REPORTED", "governance_visibility": "VISIBLE" if domain not in {"governance", "sentinel"} else "SELF_REPORTED", "cortex_visibility": "VISIBLE" if domain not in {"cortex", "sentinel", "governance"} else "SELF_REPORTED", "health": source_health, "freshness": freshness, "freshness_age_seconds": round(age, 3) if age is not None else None, "efficiency_state": _efficiency(source), "first_causal_blocker": _blocker(source), "evidence_source": source_key})
    return rows


def _funnel(stages: tuple[tuple[str, tuple[str, ...]], ...], statuses: Mapping[str, Any], *, kind: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    first = None
    for stage, keys in stages:
        key, source = _source_for(statuses, keys)
        if not source:
            state, blocker = "UNKNOWN", "NOT_MONITORED"
        else:
            state, blocker = _health(source), _blocker(source)
        row = {"stage": stage, "state": state, "evidence_source": key, "first_causal_blocker": blocker}
        rows.append(row)
        if first is None and state not in {"HEALTHY", "CACHE_FIRST_OR_UNKNOWN"}:
            first = {"stage": stage, "blocker": blocker, "evidence_source": key}
    return {"kind": kind, "stages": rows, "first_measurable_bottleneck": first or {"stage": "NONE_OBSERVED", "blocker": "NONE_OBSERVED", "evidence_source": None}}


def _control_plane(statuses: Mapping[str, Any], now: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name, keys in (("sentinel", ("astra_sentinel_integrity_v1",)), ("governance", ("astra_continuous_governance_v1", "astra_governance_coverage_consolidation_v1")), ("cortex", ("cortex_lifecycle_evidence_master_truth_v1", "astra_cortex_paper_completion_status_v1"))):
        key, source = _source_for(statuses, keys)
        age = _timestamp_age_seconds(source, now) if source else None
        stale = age is not None and age > STALE_SECONDS
        health = _health(source) if source else "UNAVAILABLE"
        if name == "governance" and stale and health == "HEALTHY":
            health = "STALE_PASS_NOT_CURRENT"
        result[name] = {"available": bool(source), "health": health, "freshness": "STALE" if stale else "CURRENT" if age is not None else "UNSPECIFIED" if source else "UNKNOWN", "freshness_age_seconds": round(age, 3) if age is not None else None, "current_status": _text(source.get("status") or source.get("current_status")) if source else "UNAVAILABLE", "current_highest_priority_issue": _blocker(source) if source else "NOT_MONITORED", "evidence_source": key}
    return result


def _priorities(domains: list[dict[str, Any]], funnels: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for domain in domains:
        if domain["health"] not in {"HEALTHY", "WARMING_UP"} or domain["freshness"] == "STALE":
            severity = "HIGH" if domain["health"] in {"FAIL", "UNAVAILABLE", "STALE_HEALTH_UNVERIFIED", "STALE_PASS_NOT_CURRENT"} else "MEDIUM"
            rows.append({"domain": domain["domain"], "issue_or_opportunity": domain["health"], "severity": severity, "evidence": domain["evidence_source"], "first_causal_blocker": domain["first_causal_blocker"], "suggested_owner": domain["canonical_owner"], "safe_autonomous_remediation_eligible": "NO", "cortex_review_required": "YES"})
    for funnel in funnels:
        bottleneck = funnel["first_measurable_bottleneck"]
        if bottleneck["stage"] != "NONE_OBSERVED" and bottleneck["blocker"] != "NOT_MONITORED":
            rows.append({"domain": funnel["kind"], "issue_or_opportunity": f"first bottleneck: {bottleneck['stage']}", "severity": "MEDIUM", "evidence": bottleneck["evidence_source"], "first_causal_blocker": bottleneck["blocker"], "suggested_owner": "existing canonical owner", "safe_autonomous_remediation_eligible": "NO", "cortex_review_required": "YES"})
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted(rows, key=lambda item: (order.get(item["severity"], 3), item["domain"], item["first_causal_blocker"]))[:5]


def build_astra_whole_platform_observability_efficiency_v1(statuses: Mapping[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    """Return a small immutable control-plane view from supplied snapshots."""
    statuses = _mapping(statuses)
    now = now or datetime.now(timezone.utc)
    domains = _domain_rows(statuses, now)
    learning = _funnel((
        ("AVAILABLE", ("astra_historical_evidence_mining_knowledge_distillation_v1",)),
        ("LOCATED", ("astra_knowledge_warehouse_v1",)),
        ("RETRIEVED_INDEXED", ("knowledge_retrieval_indexing_v1", "long_term_memory_symbol_retrieval_suite_v1")),
        ("COMPRESSED", ("astra_evidence_consumption_teacher_shadow_v1",)),
        ("OUTCOME_LINKED", ("astra_evidence_utilization_information_value_v1", "astra_trading_intelligence_improvement_suite_v5")),
        ("LEARNED_TAUGHT", ("astra_evidence_consumption_teacher_shadow_v1",)),
        ("DISTILLED", ("astra_historical_evidence_mining_knowledge_distillation_v1",)),
        ("VALIDATED", ("astra_autonomous_learning_safe_adaptation_v1",)),
        ("CORTEX_READY", ("cortex_lifecycle_evidence_master_truth_v1",)),
        ("USED", ("astra_evidence_utilization_information_value_v1",)),
    ), statuses, kind="learning")
    execution = _funnel((
        ("CANDIDATE", ("candidate_lineage_governance_v2", "paper_execution_trace")),
        ("ELIGIBLE", ("paper_execution_trace",)), ("CAPACITY", ("astra_learning_preservation_capacity_v1",)),
        ("CAPITAL_RISK", ("paper_execution_trace",)), ("ORDER_READY", ("paper_execution_trace",)),
        ("SUBMITTED", ("paper_execution_trace",)), ("FILLED", ("alpaca_paper_status_v1",)),
        ("MANAGED", ("astra_unified_position_advisory_v1",)), ("EXIT", ("astra_cortex_paper_completion_status_v1",)),
        ("RECONCILED", ("astra_trade_state_reconciliation_v1",)), ("STRICT_TRUTH", ("cortex_lifecycle_evidence_master_truth_v1",)),
        ("LEARNING_CONSUMED", ("astra_evidence_consumption_teacher_shadow_v1",)),
    ), statuses, kind="execution")
    autonomy = _funnel((
        ("FINDING", ("astra_trading_intelligence_improvement_suite_v6",)), ("HYPOTHESIS", ("astra_autonomous_learning_safe_adaptation_v1",)),
        ("SHADOW_A_B", ("astra_autonomous_learning_safe_adaptation_v1",)), ("EVIDENCE_THRESHOLD", ("astra_autonomous_learning_safe_adaptation_v1",)),
        ("CORTEX_REVIEW", ("astra_autonomous_learning_safe_adaptation_v1",)), ("GOVERNANCE", ("astra_autonomous_learning_safe_adaptation_v1", "astra_continuous_governance_v1")),
        ("CANARY", ("astra_autonomous_learning_safe_adaptation_v1",)), ("ADAPTATION", ("astra_autonomous_learning_safe_adaptation_v1",)),
        ("POST_CHANGE_VERIFICATION", ("astra_autonomous_learning_safe_adaptation_v1",)), ("RETAIN_ROLLBACK", ("astra_autonomous_learning_safe_adaptation_v1",)),
    ), statuses, kind="autonomy")
    control = _control_plane(statuses, now)
    priorities = _priorities(domains, (learning, execution, autonomy))
    gaps = [row["domain"] for row in domains if row["monitored"] == "NO"]
    degraded = [row for row in domains if row["health"] in {"FAIL", "UNAVAILABLE", "STALE_HEALTH_UNVERIFIED", "STALE_PASS_NOT_CURRENT"}]
    resource = _mapping(statuses.get("astra_runtime_resource_governance_v1"))
    adaptation = _mapping(statuses.get("astra_autonomous_learning_safe_adaptation_v1"))
    ready = bool(adaptation) and adaptation.get("behavior_safe_to_apply") is False and control["governance"]["health"] == "HEALTHY"
    return {
        "suite": "ASTRA Whole-Platform Observability, Efficiency & Control-Plane Integrity V1", "version": VERSION,
        "status": "DEGRADED" if degraded else "PARTIAL_COVERAGE" if gaps else "HEALTHY",
        "overall_status": "DEGRADED" if degraded else "PARTIAL_COVERAGE" if gaps else "HEALTHY",
        "overall_efficiency_state": "RESOURCE_CONSTRAINED" if _efficiency(resource) == "RESOURCE_CONSTRAINED" else "CACHE_FIRST_WITH_GAPS",
        "coverage_percentage": round(100.0 * (len(domains) - len(gaps)) / len(domains), 3) if domains else None,
        "coverage_percentage_note": "percentage measures registered domains with an existing snapshot; it is not a quality score",
        "domains": domains, "efficiency_scorecard": {"worker_resource_state": _efficiency(resource), "full_history_scan_count": 0, "provider_calls_added": 0, "broker_calls_added": 0, "llm_calls_added": 0, "monitoring_gaps_count": len(gaps), "observed_duplicate_authorities": 0},
        "learning_funnel": learning, "execution_funnel": execution, "autonomy_funnel": autonomy,
        "control_plane_health": control,
        "first_causal_blocker": (priorities[0].get("first_causal_blocker") if priorities else "CAUSAL_BLOCKER_UNCERTAIN"),
        "top_priorities": priorities, "monitoring_gaps": gaps,
        "efficiency_adaptation_readiness": {"status": "EFFICIENCY_ADAPTATION_READY" if ready else "EFFICIENCY_ADAPTATION_NOT_READY", "reason": "existing V7 and current Governance pass can govern a future human-reviewed shadow efficiency proposal" if ready else "existing V7/Governance facts are unavailable, stale, or not currently passing", "automatic_remediation_implemented": False, "protected_domains_preserved": True},
        "generated_at": now.isoformat().replace("+00:00", "Z"), **SAFETY,
    }
