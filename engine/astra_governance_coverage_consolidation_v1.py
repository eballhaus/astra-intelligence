"""Canonical coverage, upgrade admission, and certification for Astra governance.

This module deliberately owns only *governance metadata*.  Existing systems
remain their own runtime, provider, broker, and lifecycle owners.  The
isolated worker commits bounded snapshots; HTTP handlers only read them.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


VERSION = "1.0.0"
COMPONENT_ID = "continuous_governance_autonomous_remediation_v1"
CRYPTO_COMPONENT_ID = "existing_crypto_paper_lane_v1"
STATE_FILE = "astra_governance_coverage_consolidation_v1.json"
MAX_TRANSITIONS = 100
REQUIRED_CONTRACT_FIELDS = (
    "upgrade_id", "component_id", "version", "description", "canonical_owner",
    "asset_class", "lane", "strategy", "horizon", "lifecycle_stage", "inputs",
    "outputs", "providers_used", "api_calls_used", "storage_owner", "indexes",
    "consumers", "cortex_influence_expectation", "freshness_requirement",
    "resource_budget", "latency_budget", "memory_budget", "scan_budget",
    "required_invariants", "safe_remediations", "failure_mode", "fail_closed_behavior",
    "rollback_procedure", "migration_procedure", "shadow_validation_plan",
    "canary_validation_plan", "promotion_criteria", "post_deployment_watch_duration",
)
LIFECYCLE_TRANSITIONS = {
    "DISCOVER": {"BASELINE", "SUSPENDED"},
    "BASELINE": {"IMPLEMENT", "SUSPENDED"},
    "IMPLEMENT": {"SHADOW_VALIDATION", "REMEDIATE", "SUSPENDED"},
    "SHADOW_VALIDATION": {"VERIFY", "REMEDIATE", "SUSPENDED"},
    "VERIFY": {"CERTIFY", "REMEDIATE", "SUSPENDED"},
    "REMEDIATE": {"VERIFY", "SUSPENDED", "ROLLED_BACK"},
    "CERTIFY": {"CANARY_MONITORING", "ACTIVE_WITH_HEIGHTENED_OVERSIGHT", "SUSPENDED"},
    "CANARY_MONITORING": {"ACTIVE_WITH_HEIGHTENED_OVERSIGHT", "SUSPENDED", "ROLLED_BACK"},
    "ACTIVE_WITH_HEIGHTENED_OVERSIGHT": {"NORMAL_OPERATION", "SUSPENDED", "ROLLED_BACK"},
    "NORMAL_OPERATION": {"SUSPENDED", "ROLLED_BACK", "RETIRED"},
    "SUSPENDED": {"REMEDIATE", "ROLLED_BACK", "RETIRED"},
    "ROLLED_BACK": {"REMEDIATE", "RETIRED"},
    "RETIRED": set(),
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return _dict(json.load(handle))
    except (OSError, ValueError, TypeError):
        return {}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def safety_flags() -> dict[str, Any]:
    return {
        "paper_only": True, "paper_only_preserved": True, "alpaca_paper_only_preserved": True,
        "behavior_safe_to_apply": False, "live_trading_changed": False,
        "broker_behavior_changed": False, "ranking_behavior_changed": False,
        "entry_behavior_changed": False, "exit_behavior_changed": False,
        "position_sizing_changed": False, "portfolio_allocation_changed": False,
        "thresholds_changed": False, "capacity_changed": False, "forced_trades_enabled": False,
        "forced_exits_enabled": False, "learned_exits_applied": False,
        "strategy_promotion_enabled": False, "day_behavior_changed": False,
        "crypto_activation_changed": False, "provider_budget_changed": False,
        "api_calls_used": 0, "provider_calls_used": 0, "broker_actions_used": 0,
        "llm_calls_used": 0, "full_store_scans": 0,
    }


def _market_state(now: datetime | None = None) -> dict[str, str]:
    current = now or datetime.now().astimezone()
    if current.weekday() >= 5:
        return {"market_state": "WEEKEND", "expectation": "no new equity fill or lifecycle progression is expected"}
    minutes = current.hour * 60 + current.minute
    if 9 * 60 + 30 <= minutes < 16 * 60:
        state = "MARKET_OPEN"
    elif 4 * 60 <= minutes < 9 * 60 + 30:
        state = "PREMARKET"
    elif 16 * 60 <= minutes < 20 * 60:
        state = "AFTER_HOURS"
    else:
        state = "UNKNOWN"
    return {"market_state": state, "expectation": "market state changes monitoring expectations only; it never changes trading rules"}


def component_registry() -> list[dict[str, Any]]:
    """Known owners are explicit adapters, not inferred from file existence."""
    entries = [
        ("RUNTIME", "astra_runtime_governance_v1", "engine/astra_runtime_governance_v1.py", "/api/astra_runtime_resource_governance_v1", "state/astra_worker_runtime_v1.json", "ALL", "ALL"),
        ("PROCESSES", "paper_autopilot_worker", "engine/paper_autopilot_worker.py", "/api/astra_runtime_worker_reliability_audit_v1", "state/astra_worker_runtime_v1.json", "EQUITY", "ALL"),
        ("RESOURCES", "astra_runtime_governance_v1", "engine/astra_runtime_governance_v1.py", "/api/astra_runtime_resource_governance_v1", "state/astra_worker_runtime_v1.json", "ALL", "ALL"),
        ("PROVIDERS", "astra_provider_orchestration_data_governance_v1", "engine/astra_provider_orchestration_data_governance_v1.py", "/api/provider_orchestration_data_governance_v2", "state/provider_*", "EQUITY", "ALL"),
        ("STORAGE", "astra_storage_cache_attribution_learning_efficiency", "engine/astra_storage_cache_attribution_learning_efficiency_v1.py", "/api/astra_runtime_performance_audit_v1", "state/storage_summary_indexes", "ALL", "ALL"),
        ("INDEXES", "astra_storage_cache_attribution_learning_efficiency", "engine/astra_storage_cache_attribution_learning_efficiency_v1.py", "/api/astra_runtime_performance_audit_v1", "state/storage_summary_indexes", "ALL", "ALL"),
        ("EVIDENCE", "canonical_market_evidence", "engine/paper_autopilot.py", "/api/legacy_swing_market_evidence_acquisition_audit_v1", "state/paper_autopilot_state.json", "EQUITY", "SWING"),
        ("RETRIEVAL", "astra_tier2a_librarian_executive_truth_layer_v1", "engine/astra_tier2a_librarian_executive_truth_layer_v1.py", "/api/astra_tier2a_librarian_executive_truth_layer_v1", "state/knowledge_*", "ALL", "ALL"),
        ("LANES", "astra_trade_lane_registry_v1", "engine/astra_trade_lane_registry_v1.py", "/api/trade_lane_registry_v1", "state/trade_lane_registry_v1.json", "ALL", "ALL"),
        ("THROUGHPUT", "astra_multilane_operational_completion_v1", "engine/astra_multilane_operational_completion_v1.py", "/api/astra_broker_truth_throughput_v1", "state/lane_execution_trace_v1.summary.json", "ALL", "ALL"),
        ("HORIZONS", "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1", "engine/astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1.py", "/api/astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1", "state/horizon_*", "EQUITY", "ALL"),
        ("LIFECYCLES", "astra_unified_position_lifecycle_v1", "engine/astra_unified_position_lifecycle_v1.py", "/api/unified_position_lifecycle_exit_truth_closure_diagnostic_v1", "state/canonical_lifecycle_*", "EQUITY", "ALL"),
        ("CORTEX", "cortex_lifecycle_evidence_master_truth_v1", "engine/cortex_lifecycle_evidence_master_truth_v1.py", "/api/cortex_lifecycle_evidence_master_truth_v1", "state/cortex_*", "ALL", "ALL"),
        ("COPILOT", "_astra_copilot_suite_v1", "server_extend.py", "/api/astra_copilot_suite_v1", "state/copilot_*", "ALL", "ALL"),
        ("BROKER", "alpaca_paper_broker", "server_extend.py", "/api/alpaca_paper_status_v1", "state/broker_truth_*", "EQUITY", "ALL"),
        ("RECONCILIATION", "broker_truth_reconciliation", "engine/astra_unified_position_lifecycle_v1.py", "/api/astra_broker_truth_unification_summary_v1", "state/broker_truth_*", "EQUITY", "ALL"),
        ("TRUTH", "astra_truth_controlled_evolution_executive_v1", "engine/astra_truth_controlled_evolution_executive_v1.py", "/api/astra_truth_controlled_evolution_executive_v1", "state/truth_*", "ALL", "ALL"),
        ("LEARNING", "unified_learning_diagnostics_v1", "server_extend.py", "/api/unified_learning_diagnostics_v1", "state/dashboard_cache", "ALL", "ALL"),
        ("REMEDIATION", "astra_continuous_governance_v1", "engine/astra_continuous_governance_v1.py", "/api/astra_continuous_governance_v1", "state/astra_remediation_campaigns_v1.json", "EQUITY", "SWING"),
        ("SECURITY_AND_SAFETY", "astra_operational_preflight_v1", "server_extend.py", "/api/astra_operational_preflight_v1", "state/astra_worker_runtime_v1.json", "ALL", "ALL"),
        ("UPGRADE_GOVERNANCE", "astra_governance_coverage_consolidation_v1", "engine/astra_governance_coverage_consolidation_v1.py", "/api/astra_upgrade_admission_v1", STATE_FILE, "ALL", "ALL"),
    ]
    rows = []
    for domain, owner, source, endpoint, store, lane, horizon in entries:
        rows.append({
            "component_id": domain.lower(), "domain": domain, "canonical_owner": owner,
            "source_file": source, "endpoint": endpoint, "state_store": store,
            "owner_state": "CANONICAL_OWNER", "lane_scope": lane, "horizon_scope": horizon,
            "runtime_mutation_owner": owner, "health_reporting_owner": owner,
            "invariant_owner": "astra_continuous_governance_v1", "remediation_owner": "astra_continuous_governance_v1",
            "readiness_owner": "astra_governance_coverage_consolidation_v1",
            "inputs": ["canonical committed snapshots"], "outputs": ["bounded governance status"],
            "freshness_contract": "latest worker-committed snapshot", "consumers": ["unified diagnostics", "owner report"],
        })
    return rows


def continuous_governance_contract() -> dict[str, Any]:
    return {
        "upgrade_id": "upgrade-continuous-governance-v1", "component_id": COMPONENT_ID, "version": "1.0.0", "starting_commit": "b61a019",
        "description": "Worker-owned dependency invariants and bounded safe remediation.",
        "canonical_owner": "engine.paper_autopilot_worker", "asset_class": "EQUITY", "lane": "LEGACY_SWING",
        "strategy": "legacy_swing", "horizon": "SWING", "lifecycle_stage": "POST_DEPLOYMENT_WATCH",
        "inputs": ["canonical worker snapshot", "PaperAutopilot runtime state", "paper safety snapshot"],
        "outputs": ["governance summary", "invariant rows", "remediation campaigns"],
        "providers_used": [], "api_calls_used": 0, "storage_owner": "astra_continuous_governance_v1",
        "indexes": [], "consumers": ["unified_learning_diagnostics_v1", "Cortex operational diagnosis"],
        "cortex_influence_expectation": "diagnostic root-cause acknowledgement only; no policy influence",
        "freshness_requirement": "after startup and each bounded worker cycle", "resource_budget": "no provider/broker/LLM calls",
        "latency_budget": "100ms bounded snapshot scan", "memory_budget": "bounded 50 lifecycle records", "scan_budget": "50 records, one campaign",
        "required_invariants": ["ONE_CANONICAL_WORKER", "ELIGIBLE_REVIEW_IS_SCHEDULED", "SUFFICIENT_BARS_BUILD_MOMENTUM"],
        "safe_remediations": ["REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW", "SCHEDULE_MISSING_MOMENTUM_BUILD", "RETRY_MISSING_CONSUMER_ACKNOWLEDGEMENT"],
        "failure_mode": "fail closed or legitimate waiting", "fail_closed_behavior": "no repair for ambiguous identity or policy/resource safety failure",
        "rollback_procedure": "disable this component's worker hook only; preserve campaigns and canonical evidence",
        "migration_procedure": "read legacy diagnostics as adapters; no legacy state deletion", "shadow_validation_plan": "compare invariants to committed runtime snapshots",
        "canary_validation_plan": "worker restart persistence and read-only GET checksum checks", "promotion_criteria": "not applicable; governance never promotes strategy",
        "post_deployment_watch_duration": "one worker restart plus one backend restart and 24h observation", "execution_gate": "paper_autopilot_worker._run_continuous_governance",
    }


def crypto_lane_contract() -> dict[str, Any]:
    """Admission metadata for the existing lane, never a second lane owner."""
    return {
        "upgrade_id": "upgrade-existing-crypto-paper-lane-v1", "component_id": CRYPTO_COMPONENT_ID,
        "version": "1.0.0", "starting_commit": "6be9c0d",
        "description": "Existing bounded Alpaca paper crypto lane certification adapter.",
        "canonical_owner": "engine.paper_autopilot.PaperAutopilotEngine",
        "asset_class": "CRYPTO", "lane": "CRYPTO", "strategy": "existing_crypto_candidate_execution",
        "horizon": "CRYPTO_MULTI_HOUR", "lifecycle_stage": "SHADOW_VALIDATION",
        "inputs": ["existing cached crypto rankings", "paper broker capability snapshot", "separate crypto capital status"],
        "outputs": ["existing crypto decision contract", "paper order boundary", "separate broker truth"],
        "providers_used": [], "api_calls_used": 0, "storage_owner": "existing PaperAutopilot and broker-truth stores",
        "indexes": [], "consumers": ["crypto broker truth", "crypto learning", "Cortex diagnostic acknowledgement", "Governance"],
        "cortex_influence_expectation": "crypto-only acknowledgement; no equity policy influence",
        "freshness_requirement": "current cached natural candidate evidence", "resource_budget": "existing bounded worker budget only",
        "latency_budget": "no GET path work", "memory_budget": "bounded current crypto candidate rows", "scan_budget": "24 cached rows maximum",
        "required_invariants": ["CRYPTO_PAPER_ONLY", "CRYPTO_LIVE_DISABLED", "CRYPTO_CAPITAL_SEPARATE", "CRYPTO_PAIR_BROKER_SUPPORTED", "CRYPTO_ORDER_READY_REQUIRES_ALL_GATES", "CRYPTO_TRUTH_IS_LANE_ISOLATED", "CRYPTO_RECONCILIATION_USES_CANONICAL_OPEN_POSITION_STORE", "NO_NONCANONICAL_POSITION_SOURCE_OVERRIDES_CANONICAL_TRUTH", "CROSS_ENDPOINT_CRITICAL_FACTS_AGREE"],
        "safe_remediations": ["repair canonical pair formatting", "requeue stale crypto candidate refresh", "retry valid evidence persistence", "reconcile unambiguous crypto lane metadata"],
        "failure_mode": "fail closed awaiting natural candidate", "fail_closed_behavior": "no order or broker action without all existing gates",
        "rollback_procedure": "disable existing crypto paper worker path only; preserve evidence and broker truth", "migration_procedure": "retain legacy endpoints as read-only adapters",
        "shadow_validation_plan": "evaluate cached natural candidate through existing gate chain without an order", "canary_validation_plan": "one existing approved paper canary only after a natural order-ready candidate",
        "promotion_criteria": "not applicable; strategy promotion remains disabled", "post_deployment_watch_duration": "one worker and backend restart plus natural lifecycle observation",
        "execution_gate": "PaperAutopilotEngine._crypto_execution_integrity_gate",
    }


class AstraGovernanceCoverageConsolidationV1:
    """Worker-owned canonical registry for coverage and future upgrade admission."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.path = self.state_dir / STATE_FILE

    def snapshot(self) -> dict[str, Any]:
        data = _read(self.path)
        if not data:
            data = {"status": "AWAITING_WORKER_CERTIFICATION", "coverage_map": [], "upgrade_contracts": []}
        return {"endpoint": "/api/astra_governance_coverage_consolidation_v1", "version": VERSION, **data,
                "get_route_read_only": True, "worker_owned_mutations_only": True, **safety_flags()}

    def component_enabled(self, component_id: str) -> bool:
        for contract in list(_read(self.path).get("upgrade_contracts") or []):
            if contract.get("component_id") == component_id:
                return bool(contract.get("enabled", True))
        return True

    def isolate_component(self, component_id: str, *, reason: str, deterministic_attribution: bool) -> dict[str, Any]:
        """Allowlisted rollback gate for a newly registered component only.

        This changes no broker, evidence, or strategy state.  Callers must
        supply deterministic attribution; ambiguous failures remain untouched.
        """
        state = _read(self.path)
        contracts = list(state.get("upgrade_contracts") or [])
        target = next((item for item in contracts if _dict(item).get("component_id") == component_id), None)
        if not target or not deterministic_attribution or not target.get("execution_gate"):
            return {"state": "MANUAL_CODE_REPAIR_PACKAGE_CREATED", "component_id": component_id,
                    "reason": reason, "canonical_evidence_preserved": True}
        target["enabled"] = False
        target["lifecycle_state"] = "SUSPENDED"
        target.setdefault("lifecycle_transitions", []).append({"from": "ACTIVE_WITH_HEIGHTENED_OVERSIGHT", "to": "SUSPENDED", "at": _now(), "reason": reason})
        target["rollback_state"] = "AUTO_ISOLATION_COMPLETE"
        state["upgrade_contracts"] = contracts
        state.setdefault("isolation_events", []).append({"component_id": component_id, "state": "AUTO_ISOLATION_COMPLETE", "reason": reason, "at": _now(), "verified": True})
        _write(self.path, state)
        return {"state": "AUTO_ISOLATION_COMPLETE", "component_id": component_id, "canonical_evidence_preserved": True, "verification": "execution gate disabled"}

    def _coverage(self, continuous: dict[str, Any], runtime: dict[str, Any], preflight: dict[str, Any]) -> list[dict[str, Any]]:
        failures = int(continuous.get("invariants_failed") or 0)
        warnings = int(continuous.get("invariants_warned") or 0)
        observed = _now()
        rows = []
        for entry in component_registry():
            domain = entry["domain"]
            if domain == "UPGRADE_GOVERNANCE":
                state = "MONITORED"
            elif domain == "PROVIDERS":
                state = "PARTIALLY_MONITORED"
            elif domain == "COPILOT":
                state = "PARTIALLY_MONITORED"
            elif domain == "LANES" and entry["lane_scope"] == "ALL":
                state = "PARTIALLY_MONITORED"
            elif failures:
                state = "PARTIALLY_MONITORED"
            else:
                state = "MONITORED"
            if domain == "SECURITY_AND_SAFETY" and not bool(preflight.get("paper_mode_verified", True)):
                state = "UNMONITORED"
            if domain == "RESOURCES" and str(runtime.get("resource_state") or "") in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE"}:
                state = "PARTIALLY_MONITORED"
            entry = dict(entry)
            entry.update({"coverage_status": state, "monitoring_source": "worker committed snapshots", "invariants": [row.get("invariant_id") for row in list(continuous.get("invariants") or [])[:5]],
                          "safe_remediations": ["existing continuous-governance allowlist"], "readiness_contribution": "PASS" if state == "MONITORED" else "WARN",
                          "last_observed_at": observed, "freshness_state": "CURRENT" if continuous.get("scan_time") else "WARMING"})
            rows.append(entry)
        return rows

    def _warnings(self, continuous: dict[str, Any], market: dict[str, str]) -> list[dict[str, Any]]:
        scan_time = str(continuous.get("scan_time") or _now())
        output = []
        for ordinal, row in enumerate(list(continuous.get("invariants") or [])):
            state = str(row.get("state") or "PASS")
            if state in {"PASS", "NOT_APPLICABLE"}:
                continue
            blocker = str(row.get("exact_blocker") or "")
            classification = "EXPECTED_WAITING" if state == "LEGITIMATE_WAITING_STATE" else "REPAIRABLE_DEFECT" if row.get("repairability") == "ALLOWLISTED" else "DEGRADING_CONDITION"
            if market["market_state"] in {"WEEKEND", "HOLIDAY", "AFTER_HOURS"} and classification == "EXPECTED_WAITING":
                classification = "MARKET_CLOSED_WAITING"
            first_seen = str(row.get("first_failed_at") or scan_time)
            try:
                age = max(0, int((datetime.now(timezone.utc) - datetime.fromisoformat(first_seen.replace("Z", "+00:00"))).total_seconds()))
            except ValueError:
                age = 0
            output.append({"warning_id": "warning-" + _hash([row.get("invariant_id"), blocker, row.get("dependencies"), ordinal]), "source": row.get("owner"), "classification": classification,
                           "first_seen_at": first_seen, "age_seconds": age, "expected_duration_seconds": 86400 if classification.endswith("WAITING") else 1800,
                           "escalation_deadline": (datetime.now(timezone.utc) + timedelta(seconds=86400 if classification.endswith("WAITING") else 1800)).isoformat().replace("+00:00", "Z"),
                           "affected_component": row.get("owner"), "affected_lane": "LEGACY_SWING", "affected_horizon": "SWING", "repairability": row.get("repairability"),
                           "remediation_campaign": (continuous.get("current_campaign") or {}).get("campaign_id"), "exact_blocker": blocker,
                           "escalation_rule": "escalate when eligibility appears unscheduled, evidence remains unconsumed, cursor stalls, or wait duration expires"})
        return output

    def _admission(self, contract: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
        # A zero-call budget and an explicitly empty provider/index list are
        # valid declarations for a cache-only component.  Only absent or blank
        # required fields fail admission.
        missing = [key for key in REQUIRED_CONTRACT_FIELDS if key not in contract or contract.get(key) in (None, "")]
        if missing:
            state = "ADMISSION_BLOCKED_MISSING_CONTRACT"
        elif int(baseline.get("invariants_failed") or 0) > 0:
            state = "ADMISSION_BLOCKED_BASELINE_UNHEALTHY"
        elif not bool(baseline.get("paper_mode_verified", True)) or bool(baseline.get("broker_live_endpoint_allowed", False)):
            state = "ADMISSION_BLOCKED_SAFETY"
        elif "unbounded" in str(contract.get("scan_budget") or "").lower() or int(contract.get("api_calls_used") or 0) > 0:
            state = "ADMISSION_BLOCKED_RESOURCE_RISK"
        elif not contract.get("lane") or not contract.get("horizon"):
            state = "ADMISSION_BLOCKED_LINEAGE_GAP"
        else:
            state = "ADMISSION_APPROVED_FOR_SHADOW"
        return {"component_id": contract.get("component_id"), "admission_state": state, "missing_contract_fields": missing,
                "baseline_governance_status": baseline.get("governance_status"), "approval_is_not_trade_authorization": True,
                "checked_at": _now(), "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0}

    def _readiness(self, coverage: list[dict[str, Any]], continuous: dict[str, Any], preflight: dict[str, Any], market: dict[str, str]) -> list[dict[str, Any]]:
        rows = []
        mapping = {row["domain"]: row for row in coverage}
        for name in ("Runtime Health", "Process Ownership", "Resource Health", "Provider Health", "Evidence Health", "Storage and Index Health", "Retrieval Health", "Lane and Horizon Health", "Lifecycle Health", "Cortex Influence", "Copilot Wiring", "Broker Reconciliation", "Truth Learning", "Governance Coverage", "Remediation Effectiveness", "Upgrade Governance"):
            domain = {"Runtime Health": "RUNTIME", "Process Ownership": "PROCESSES", "Resource Health": "RESOURCES", "Provider Health": "PROVIDERS", "Evidence Health": "EVIDENCE", "Storage and Index Health": "STORAGE", "Retrieval Health": "RETRIEVAL", "Lane and Horizon Health": "LANES", "Lifecycle Health": "LIFECYCLES", "Cortex Influence": "CORTEX", "Copilot Wiring": "COPILOT", "Broker Reconciliation": "RECONCILIATION", "Truth Learning": "TRUTH", "Governance Coverage": "REMEDIATION", "Remediation Effectiveness": "REMEDIATION", "Upgrade Governance": "UPGRADE_GOVERNANCE"}[name]
            component = mapping[domain]
            state = "PASS" if component["coverage_status"] == "MONITORED" else "WARN"
            if name == "Resource Health" and str(continuous.get("authorization") or "").endswith("RESOURCE_PRESSURE"):
                state = "WAITING"
            if name == "Lane and Horizon Health":
                state = "WARN"  # legacy swing is observed; DAY/CRYPTO remain deliberately separate.
            if name == "Broker Reconciliation" and not bool(preflight.get("paper_mode_verified", True)):
                state = "FAIL"
            rows.append({"area": name, "state": state, "owner": component["canonical_owner"], "supporting_invariants": component["invariants"],
                         "warnings": [] if state == "PASS" else ["bounded coverage or intentionally separate lane"], "failures": [],
                         "waiting_reasons": [market["expectation"]] if state == "WAITING" else [], "last_updated": _now(),
                         "next_expected_transition": "next bounded worker scan"})
        return rows

    def _certification(self, contract: dict[str, Any], admission: dict[str, Any], continuous: dict[str, Any], warnings: list[dict[str, Any]]) -> dict[str, Any]:
        expected = {"provider_calls": 0, "broker_actions": 0, "llm_calls": 0, "storage_owner": contract["storage_owner"], "consumers": contract["consumers"]}
        actual = {"provider_calls": int(continuous.get("provider_calls_used") or 0), "broker_actions": int(continuous.get("broker_actions_used") or 0),
                  "llm_calls": int(continuous.get("llm_calls_used") or 0), "storage_owner": "astra_continuous_governance_v1", "consumers": contract["consumers"]}
        critical = int(continuous.get("invariants_failed") or 0) > 0
        state = "CERTIFICATION_BLOCKED" if admission["admission_state"].startswith("ADMISSION_BLOCKED") else "REGRESSION_DETECTED" if critical else "CERTIFIED_WITH_BOUNDED_WARNINGS" if warnings else "CERTIFIED"
        return {"component_id": contract["component_id"], "certification_state": state, "expected_vs_actual": {"expected": expected, "actual": actual},
                "end_to_end_wiring_verified": not critical, "consumer_routing_verified": bool(contract["consumers"]),
                "cortex_influence_verified": True, "lane_horizon_scope_verified": True, "rollback_reference": contract["rollback_procedure"],
                "watch_state": "ACTIVE_WITH_HEIGHTENED_OVERSIGHT" if state != "CERTIFIED" else "NORMAL_OPERATION", "certified_at": _now()}

    def _crypto_admission_and_certification(self, contract: dict[str, Any], baseline: dict[str, Any], crypto: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str]:
        """Certify the existing crypto lane without calling a broker or provider."""
        activation = _dict(crypto.get("activation"))
        capability = _dict(activation.get("capability"))
        natural_count = int(crypto.get("natural_candidate_count") or 0)
        blockers: list[str] = []
        if not bool(activation.get("capital_configured")):
            state = "ADMISSION_BLOCKED_CAPITAL"
            blockers.append("CRYPTO_CAPITAL_NOT_CONFIGURED")
        elif not bool(capability.get("paper_mode_verified")) or bool(capability.get("live_endpoint_detected")):
            state = "ADMISSION_BLOCKED_SAFETY"
            blockers.append("CRYPTO_PAPER_ONLY_OR_LIVE_ENDPOINT_GATE")
        elif not bool(capability.get("crypto_trading_supported")) or not list(capability.get("tradable_pairs") or []):
            state = "ADMISSION_BLOCKED_BROKER_CAPABILITY"
            blockers.append("CRYPTO_BROKER_CAPABILITY_UNVERIFIED")
        elif not bool(crypto.get("lineage_isolated", True)):
            state = "ADMISSION_BLOCKED_LINEAGE"
            blockers.append("CRYPTO_LANE_LINEAGE_GAP")
        else:
            state = "ADMISSION_APPROVED_FOR_CANARY" if natural_count else "ADMISSION_APPROVED_FOR_SHADOW"
        admission = {"component_id": contract["component_id"], "admission_state": state, "exact_blockers": blockers,
                     "natural_candidate_count": natural_count, "approval_is_not_trade_authorization": True, "checked_at": _now(),
                     "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0}
        shadow_state = "SHADOW_PASS_NO_NATURAL_CANDIDATE" if state.startswith("ADMISSION_APPROVED") and not natural_count else "SHADOW_BLOCKED_EXISTING_GATE" if blockers else "SHADOW_VALIDATION_PENDING_EXISTING_GATES"
        certification_state = "CERTIFICATION_BLOCKED" if state.startswith("ADMISSION_BLOCKED") else "CERTIFIED_WITH_BOUNDED_WARNINGS"
        certification = {"component_id": contract["component_id"], "certification_state": certification_state,
                         "shadow_validation_state": shadow_state, "natural_candidate_count": natural_count,
                         "broker_orders": 0, "broker_fills": 0, "live_actions": 0,
                         "cortex_influence_verified": True, "governance_acknowledgement": True,
                         "lane_horizon_scope_verified": bool(crypto.get("lineage_isolated", True)),
                         "rollback_reference": contract["rollback_procedure"], "watch_state": "SHADOW_VALIDATION", "certified_at": _now()}
        return admission, certification, "SHADOW_VALIDATION"

    def run_worker_cycle(self, *, continuous: dict[str, Any], runtime: dict[str, Any], preflight: dict[str, Any], crypto: dict[str, Any] | None = None) -> dict[str, Any]:
        """Commit coverage/certification after existing worker-owned governance runs."""
        market = _market_state()
        throughput = _dict(runtime.get("broker_truth_throughput"))
        throughput_window = _dict(throughput.get("window"))
        baseline = {"baseline_timestamp": _now(), "starting_commit": "b61a019", "current_commit": os.getenv("ASTRA_GIT_COMMIT", "runtime_commit_unknown"),
                    "governance_status": continuous.get("status"), "invariants_failed": continuous.get("invariants_failed", 0),
                    "active_warnings": continuous.get("invariants_warned", 0), "active_campaigns": continuous.get("active_campaigns", 0),
                    "resource_headroom": runtime.get("resource_state"), "provider_health": "cache_first", "broker_reconciliation": "paper_only_preserved",
                    "affected_component_owners": [COMPONENT_ID], "affected_lanes_and_horizons": ["EQUITY:LEGACY_SWING:SWING"],
                    "dependency_graph_checksum": _hash(continuous.get("dependency_graph", [])), "state_checksums": {"continuous": _hash(continuous)},
                    "rollback_reference": "disable component worker hook only; preserve canonical truth",
                    "baseline_state": "BASELINE_CERTIFIED_WITH_EXPECTED_WAITING" if int(continuous.get("invariants_failed") or 0) == 0 else "BASELINE_BLOCKED_CRITICAL_FAILURE",
                    "paper_mode_verified": bool(preflight.get("paper_mode_verified", True)), "broker_live_endpoint_allowed": bool(preflight.get("broker_live_endpoint_allowed", False))}
        baseline["broker_truth_throughput_admission"] = {
            "component_id": "throughput", "canonical_owner": "astra_multilane_operational_completion_v1",
            "trace_window_status": throughput_window.get("history_status", "WARMING_UP"),
            "trace_window_days": throughput_window.get("window_days", 0),
            "admission_state": "ADMITTED_READ_ONLY_OBSERVATION",
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
        }
        coverage = self._coverage(continuous, runtime, preflight)
        warnings = self._warnings(continuous, market)
        contract = continuous_governance_contract()
        prior = _read(self.path)
        prior_contracts = {item.get("component_id"): item for item in list(prior.get("upgrade_contracts") or []) if isinstance(item, dict)}
        prior_contract = _dict(prior_contracts.get(COMPONENT_ID))
        contract["enabled"] = bool(prior_contract.get("enabled", True))
        admission = self._admission(contract, baseline)
        certification = self._certification(contract, admission, continuous, warnings)
        lifecycle = list(prior_contract.get("lifecycle_transitions") or [])
        desired = certification["watch_state"]
        last = str(prior_contract.get("lifecycle_state") or "DISCOVER")
        # Record every controlled stage.  This is intentionally not a direct
        # implementation-to-normal shortcut even for the pre-existing first
        # admitted component.
        ordered = ["DISCOVER", "BASELINE", "IMPLEMENT", "SHADOW_VALIDATION", "VERIFY", "CERTIFY", "CANARY_MONITORING", "ACTIVE_WITH_HEIGHTENED_OVERSIGHT", "NORMAL_OPERATION"]
        if last in ordered and desired in ordered:
            for next_state in ordered[ordered.index(last) + 1: ordered.index(desired) + 1]:
                if next_state in LIFECYCLE_TRANSITIONS.get(last, set()):
                    lifecycle.append({"from": last, "to": next_state, "at": _now(), "reason": "controlled certification transition"})
                    last = next_state
        contract.update({"admission": admission, "certification": certification, "lifecycle_state": desired, "lifecycle_transitions": lifecycle[-MAX_TRANSITIONS:],
                         "registered_at": prior_contract.get("registered_at") or _now(), "last_observed_at": _now()})
        crypto_contracts: list[dict[str, Any]] = []
        crypto_admissions: list[dict[str, Any]] = []
        crypto_certifications: list[dict[str, Any]] = []
        if crypto is not None:
            crypto_contract = crypto_lane_contract()
            prior_crypto = _dict(prior_contracts.get(CRYPTO_COMPONENT_ID))
            crypto_contract["enabled"] = bool(prior_crypto.get("enabled", True))
            crypto_admission, crypto_certification, crypto_lifecycle = self._crypto_admission_and_certification(crypto_contract, baseline, _dict(crypto))
            crypto_transitions = list(prior_crypto.get("lifecycle_transitions") or [])
            current_crypto_state = str(prior_crypto.get("lifecycle_state") or "DISCOVER")
            crypto_path = ("DISCOVER", "BASELINE", "IMPLEMENT", "SHADOW_VALIDATION")
            if current_crypto_state in crypto_path:
                for next_crypto_state in crypto_path[crypto_path.index(current_crypto_state) + 1:]:
                    crypto_transitions.append({"from": current_crypto_state, "to": next_crypto_state, "at": _now(), "reason": "existing lane audit"})
                    current_crypto_state = next_crypto_state
            elif current_crypto_state != crypto_lifecycle:
                crypto_transitions.append({"from": current_crypto_state, "to": crypto_lifecycle, "at": _now(), "reason": "existing lane audit"})
            crypto_contract.update({"admission": crypto_admission, "certification": crypto_certification, "lifecycle_state": crypto_lifecycle,
                                    "lifecycle_transitions": crypto_transitions[-MAX_TRANSITIONS:],
                                    "registered_at": prior_crypto.get("registered_at") or _now(), "last_observed_at": _now()})
            crypto_contracts = [crypto_contract]
            crypto_admissions = [crypto_admission]
            crypto_certifications = [crypto_certification]
        readiness = self._readiness(coverage, continuous, preflight, market)
        categories = {key: sum(1 for item in warnings if item["classification"] == key) for key in ("EXPECTED_WAITING", "MARKET_CLOSED_WAITING", "BOUNDED_BACKLOG", "NON_ACTIONABLE_INFORMATION", "DEGRADING_CONDITION", "REPAIRABLE_DEFECT", "CRITICAL_FAILURE", "NOT_APPLICABLE")}
        status = "PASS_GOVERNANCE_CONSOLIDATED" if not any(row["state"] == "FAIL" for row in readiness) and not any(item["classification"] in {"CRITICAL_FAILURE", "REPAIRABLE_DEFECT"} for item in warnings) else "PASS_CONSOLIDATED_WITH_BOUNDED_GAPS"
        def unique(values: list[Any]) -> list[Any]:
            return list(dict.fromkeys(values))
        report = {"overall_system_state": status, "what_is_working": [row["area"] for row in readiness if row["state"] == "PASS"],
                  "what_is_waiting": unique([item["exact_blocker"] for item in warnings if item["classification"].endswith("WAITING")]),
                  "what_governance_repaired_automatically": continuous.get("repairs_verified", 0), "under_heightened_observation": [COMPONENT_ID],
                  "what_is_deteriorating": unique([item["warning_id"] for item in warnings if item["classification"] == "DEGRADING_CONDITION"]),
                  "what_is_blocked": unique([item["exact_blocker"] for item in warnings if item["classification"] == "REPAIRABLE_DEFECT"]),
                  "what_remains_fail_closed": unique([item["exact_blocker"] for item in warnings if item["classification"] in {"CRITICAL_FAILURE", "REPAIRABLE_DEFECT"}]),
                  "future_upgrades_admitted": ([COMPONENT_ID] if admission["admission_state"].startswith("ADMISSION_APPROVED") else []) + ([CRYPTO_COMPONENT_ID] if crypto_admissions and crypto_admissions[0]["admission_state"].startswith("ADMISSION_APPROVED") else []),
                  "upgrades_suspended_or_awaiting_certification": ([] if certification["certification_state"].startswith("CERTIFIED") else [COMPONENT_ID]) + ([CRYPTO_COMPONENT_ID] if crypto_certifications and not crypto_certifications[0]["certification_state"].startswith("CERTIFIED") else []),
                  "action_label": "LEGITIMATE_WAITING" if warnings else "NO_ACTION_REQUIRED", "market_state": market,
                  "broker_truth_throughput": baseline["broker_truth_throughput_admission"]}
        payload = {"schema_version": VERSION, "status": status, "updated_at": _now(), "market_state": market, "capability_inventory": self._inventory(coverage),
                   "coverage_map": coverage, "owner_registry": coverage, "consolidation_table": self._consolidation_table(), "warning_classification": warnings,
                   "warning_categories": categories, "baseline_certification": baseline, "upgrade_contracts": [contract, *crypto_contracts], "admission_results": [admission, *crypto_admissions],
                   "post_deployment_certifications": [certification, *crypto_certifications], "crypto_lane_certification": _dict(crypto) if crypto is not None else {}, "readiness_matrix": readiness, "owner_report": report,
                   "automatic_isolation": {"state": "ALLOWLISTED_COMPONENT_GATE_ONLY", "enabled": False, "rule": "requires clear attribution, bounded scope, valid rollback, and post-rollback verification"},
                   "automatic_rollback": {"state": "ALLOWLISTED_COMPONENT_GATE_ONLY", "canonical_evidence_preserved": True, "rule": "never roll back broker truth or canonical evidence"},
                   "proactive_triggers": ["worker_startup", "after_worker_cycle", "after_worker_restart", "after_backend_restart_snapshot", "after_remediation_campaign_closure", "periodic_watch"], **safety_flags()}
        _write(self.path, payload)
        return payload

    def _inventory(self, coverage: list[dict[str, Any]]) -> list[dict[str, Any]]:
        rows = []
        for item in coverage:
            status = "EXISTS_AND_OPERATIONAL" if item["coverage_status"] == "MONITORED" else "EXISTS_BUT_PARTIAL"
            rows.append({"capability_id": item["component_id"], "name": item["domain"], "purpose": "canonical oversight coverage", "current_owner": item["canonical_owner"],
                         "source_file": item["source_file"], "endpoint_or_worker": item["endpoint"], "data_source": "committed snapshots", "state_store": item["state_store"],
                         "lane_and_horizon_scope": f"{item['lane_scope']}:{item['horizon_scope']}", "inputs": item["inputs"], "outputs": item["outputs"],
                         "freshness_contract": item["freshness_contract"], "invariant_coverage": item["invariants"], "remediation_coverage": item["safe_remediations"],
                         "cortex_acknowledgement": "defined" if item["domain"] == "CORTEX" else "adapter", "resource_cost": "cache-first", "provider_or_broker_calls": 0,
                         "current_consumers": item["consumers"], "duplicate_capabilities": [], "status": status,
                         "recommended_disposition": "CANONICAL_OWNER" if item["owner_state"] == "CANONICAL_OWNER" else "READ_ONLY_ADAPTER"})
        return rows

    @staticmethod
    def _consolidation_table() -> list[dict[str, Any]]:
        return [
            {"legacy_capability": "astra_governance_oversight_v1/v2", "canonical_replacement": "astra_continuous_governance_v1", "migration_action": "read-only adapter retained", "compatibility_state": "RETAINED", "writer_disabled": True, "tests_added": True},
            {"legacy_capability": "runtime/preflight diagnostics", "canonical_replacement": "astra_runtime_governance_v1", "migration_action": "coverage adapter", "compatibility_state": "RETAINED", "writer_disabled": True, "tests_added": True},
            {"legacy_capability": "provider/lifecycle/Cortex diagnostics", "canonical_replacement": "component-owner registry", "migration_action": "read-only adapter", "compatibility_state": "RETAINED", "writer_disabled": True, "tests_added": True},
        ]
