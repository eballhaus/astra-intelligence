"""V7 read-only adaptation proposal and safe-promotion orchestration."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_shadow_experiment_governance_v1 import experiment_contract
from engine.astra_trading_intelligence_improvement_v2 import _number, _read
from engine.astra_trading_intelligence_improvement_v6 import SAFETY as V6_SAFETY, build_trading_intelligence_improvement_suite_v6


VERSION = "1.0.0"
ALLOWED_DOMAINS = {
    "evidence_weighting", "confidence_calibration", "symbol_preference", "regime_preference",
    "archetype_preference", "catalyst_preference", "horizon_preference", "entry_timing_preference",
    "hold_duration_expectations", "profit_protection_sensitivity", "opportunity_cost_sensitivity",
    "replacement_candidate_preference", "research_prioritization",
}
HARD_PROTECTED_DOMAINS = {
    "broker_authority", "live_trading_boundary", "strict_truth_eligibility", "lifecycle_identity",
    "reconciliation_requirements", "hard_loss_limits", "maximum_absolute_exposure", "credentials",
}
SAFETY = {
    **V6_SAFETY,
    "adaptation_behavior_changed": False,
    "active_adaptation_count": 0,
    "automatic_promotion_authority": False,
    "owner_notification_dispatches": 0,
    "state_mutations_from_get": 0,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "UNAVAILABLE") -> str:
    value = str(value or "").strip()
    return value.upper() if value else default


def _governance_pass(v6: Mapping[str, Any], override: Mapping[str, Any] | None) -> dict[str, Any]:
    if override is not None:
        passed = bool(override.get("passed"))
        return {"status": "PASS" if passed else "FAIL", "source": "EXPLICIT_EXISTING_GOVERNANCE_SNAPSHOT", "passed": passed, "reason": override.get("reason") or "governance_snapshot"}
    safe = (
        v6.get("behavior_safe_to_apply") is False
        and v6.get("execution_behavior_changed") is False
        and v6.get("paper_only_preserved") is True
        and v6.get("live_trading_changed") is False
    )
    return {"status": "PASS" if safe else "FAIL", "source": "V1_V6_SAFETY_CONTRACT", "passed": safe, "reason": "existing_paper_only_fail_closed_flags" if safe else "safety_contract_incomplete"}


def _proposal(v6: Mapping[str, Any], domain: str) -> dict[str, Any]:
    domain = str(domain or "research_prioritization").strip().lower()
    strict = int(_number(v6.get("strict_truth_sample_size")) or 0)
    shadow = int(_number(v6.get("shadow_sample_size_separate")) or 0)
    readiness = dict(v6.get("learning_promotion_readiness") or {})
    if domain in HARD_PROTECTED_DOMAINS or domain not in ALLOWED_DOMAINS:
        state, reason = "NOT_ALLOWED", "ADAPTATION_NOT_ALLOWED"
    elif strict < 5:
        state, reason = "INSUFFICIENT_EVIDENCE", "STRICT_TRUTH_SAMPLE_BELOW_5"
    elif readiness.get("status") in {"NOT_READY", "COLLECT_MORE_EVIDENCE"}:
        state, reason = "CONTINUE_OBSERVATION", "V6_PROMOTION_READINESS_NOT_MET"
    else:
        state, reason = "SHADOW_TEST_CANDIDATE", "BOUNDED_SHADOW_COMPARISON_REQUIRED"
    return {
        "adaptation_id": f"v7:{domain}:baseline_to_candidate", "created_at": _now(), "domain": domain,
        "scope": "OBSERVATIONAL_ONLY", "current_method_version": "METHOD_A_BASELINE",
        "proposed_method_version": "METHOD_B_CANDIDATE", "current_method_summary": "existing canonical method unchanged",
        "proposed_change_summary": "bounded versioned candidate only; no policy mutation",
        "reason": reason, "state": state, "strict_truth_sample_size": strict,
        "shadow_sample_size": shadow, "relevant_lane": "UNAVAILABLE", "relevant_horizon": "UNAVAILABLE",
        "relevant_regime": "UNAVAILABLE", "expected_benefit": "UNAVAILABLE_WITHOUT_STRICT_REPEATABILITY",
        "potential_downside": "REGIME_SPECIFIC_OVERFIT", "evidence_quality": readiness.get("learning_complete_truths", 0),
        "evidence_completeness": readiness.get("learning_complete_truths", 0),
        "drift_state": readiness.get("v4_drift_status", "INSUFFICIENT_EVIDENCE"),
        "supporting_evidence": [reason], "contradictory_evidence": ["STRICT_TRUTH_EVIDENCE_INSUFFICIENT"],
        "proposed_validation_path": "METHOD_A_AND_B_SAME_TIMESTAMP_VALID_SHADOW_INPUTS",
        "automatic_apply_allowed": False,
    }


def _shadow_ab(shadow: Mapping[str, Any], proposal: Mapping[str, Any]) -> dict[str, Any]:
    experiment = dict(shadow.get("ab_validation") or {})
    baseline = dict(experiment.get("baseline") or {})
    candidate = dict(experiment.get("candidate") or {})
    sample = min(int(_number(baseline.get("sample_size")) or 0), int(_number(candidate.get("sample_size")) or 0))
    timestamp_valid = bool(experiment.get("timestamp_valid_evidence_only"))
    baseline_return, candidate_return = _number(baseline.get("expectancy")), _number(candidate.get("expectancy"))
    baseline_drawdown, candidate_drawdown = _number(baseline.get("drawdown")), _number(candidate.get("drawdown"))
    if proposal.get("state") != "SHADOW_TEST_CANDIDATE":
        status = "INSUFFICIENT_EVIDENCE"
    elif not timestamp_valid or sample < 20:
        status = "CONTINUE_SHADOW_VALIDATION"
    elif candidate_return is not None and baseline_return is not None and candidate_return > baseline_return and (candidate_drawdown is None or baseline_drawdown is None or candidate_drawdown <= baseline_drawdown):
        status = "CANDIDATE_BETTER"
    elif candidate_return is not None and baseline_return is not None and candidate_return < baseline_return:
        status = "BASELINE_BETTER"
    else:
        status = "MIXED"
    return {
        "status": status, "method_a": {"version": "METHOD_A_BASELINE", **baseline},
        "method_b": {"version": "METHOD_B_CANDIDATE", **candidate}, "comparable_sample_size": sample,
        "same_timestamp_valid_evidence_only": timestamp_valid,
        "lookahead_contamination_detected": not timestamp_valid,
        "shadow_is_not_broker_truth": True, "shadow_weight_below_strict_truth": True,
        "validation_contract": experiment_contract(
            hypothesis=proposal.get("proposed_change_summary"), current_production_paper_baseline="METHOD_A_BASELINE",
            proposed_change="METHOD_B_CANDIDATE", minimum_sample_size=20,
            success_criteria="candidate improves overall quality without worse drawdown",
            failure_criteria="candidate underperforms or lacks timestamp-valid evidence",
            current_state="RESEARCH_ONLY",
        ),
    }


def _cortex_decision(proposal: Mapping[str, Any], shadow_ab: Mapping[str, Any], governance: Mapping[str, Any]) -> dict[str, Any]:
    if proposal.get("state") == "NOT_ALLOWED":
        decision, reason = "REJECT_CHANGE", "DOMAIN_NOT_ALLOWLISTED"
    elif not governance.get("passed"):
        decision, reason = "REJECT_CHANGE", "GOVERNANCE_BOUNDARY_FAILED"
    elif proposal.get("state") in {"INSUFFICIENT_EVIDENCE", "CONTINUE_OBSERVATION"}:
        decision, reason = "COLLECT_MORE_EVIDENCE", proposal.get("reason")
    elif shadow_ab.get("status") in {"INSUFFICIENT_EVIDENCE", "CONTINUE_SHADOW_VALIDATION"}:
        decision, reason = "CONTINUE_SHADOW", "SHADOW_A_B_NOT_MATURE"
    elif shadow_ab.get("status") == "CANDIDATE_BETTER" and int(proposal.get("strict_truth_sample_size") or 0) >= 20:
        decision, reason = "CANARY_ELIGIBLE", "STRICT_AND_SHADOW_EVIDENCE_GATE_MET"
    else:
        decision, reason = "COLLECT_MORE_EVIDENCE", "OVERALL_TRADING_QUALITY_NOT_PROVEN"
    return {"authority": "CORTEX", "decision": decision, "reason": reason, "governance_required": True, "automatic_execution_change": False}


def _canary(proposal: Mapping[str, Any], cortex: Mapping[str, Any]) -> dict[str, Any]:
    eligible = cortex.get("decision") == "CANARY_ELIGIBLE"
    return {
        "state": "CANARY_ELIGIBLE" if eligible else "NOT_READY", "activation_state": "NOT_ACTIVATED_NO_VERSIONED_POLICY_HOOK",
        "adaptation_id": proposal.get("adaptation_id"), "allowed_lane": proposal.get("relevant_lane"),
        "maximum_sample_count": 5, "maximum_duration": "5_broker_confirmed_closures", "maximum_capital_scope": "NO_CAPITAL_SCOPE_CHANGE",
        "baseline_method_version": proposal.get("current_method_version"), "candidate_method_version": proposal.get("proposed_method_version"),
        "rollback_trigger": "SAFETY_VIOLATION_OR_MATERIAL_UNDERPERFORMANCE", "automatic_paper_activation": False,
    }


def _owner_notice(proposal: Mapping[str, Any], cortex: Mapping[str, Any], governance: Mapping[str, Any], canary: Mapping[str, Any]) -> dict[str, Any]:
    actionable = cortex.get("decision") in {"CANARY_ELIGIBLE", "ROLLBACK_REQUIRED"}
    return {
        "status": "NOTIFICATION_PREPARED" if actionable else "NO_STATE_CHANGE_NO_NOTIFICATION_DISPATCHED",
        "dispatch_required_before_state_change": True, "dispatch_performed": False,
        "plain_english": (
            f"Astra reviewed {proposal.get('domain')}. Cortex decided {cortex.get('decision')} because "
            f"{cortex.get('reason')}. Strict truths: {proposal.get('strict_truth_sample_size')}; "
            f"Shadow comparisons: {proposal.get('shadow_sample_size')}. Canary status: {canary.get('state')}."
        ),
        "rollback_status": "ARMED_BASELINE_PRESERVED", "governance_status": governance.get("status"),
    }


def build_autonomous_learning_safe_adaptation_v1(
    state_dir: str = "state", query: Mapping[str, Any] | None = None, *, governance_override: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return proposal/readiness contracts without applying an adaptation."""
    state = Path(state_dir)
    query = query or {}
    v6 = build_trading_intelligence_improvement_suite_v6(state_dir, query)
    shadow = _read(state / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json")
    proposal = _proposal(v6, str(query.get("domain") or "research_prioritization"))
    shadow_ab = _shadow_ab(shadow, proposal)
    governance = _governance_pass(v6, governance_override)
    cortex = _cortex_decision(proposal, shadow_ab, governance)
    canary = _canary(proposal, cortex)
    notice = _owner_notice(proposal, cortex, governance, canary)
    return {
        "suite": "ASTRA Autonomous Learning & Safe Adaptation Suite V7", "version": VERSION,
        "status": "SHADOW_PRACTICE" if proposal.get("state") != "NOT_ALLOWED" else "NOT_ALLOWED",
        "adaptation_candidate_generator": proposal, "shadow_ab_validation": shadow_ab,
        "cortex_adaptation_decision": cortex, "governance_boundary": governance,
        "bounded_canary_controller": canary,
        "rollback": {"status": "ARMED", "baseline_preserved": True, "arbitrary_source_rollback": False, "rollback_required_on": canary.get("rollback_trigger")},
        "owner_notification": notice,
        "adaptation_ledger": {"mode": "READ_ONLY_PREVIEW", "active_adaptation_count": 0, "entries": [{"proposal": proposal, "cortex": cortex, "governance": governance, "canary": canary, "owner_notice": notice}]},
        "allowed_adaptation_domains": sorted(ALLOWED_DOMAINS), "protected_hard_domains": sorted(HARD_PROTECTED_DOMAINS),
        "v1_v6_continuity": {"v6_status": v6.get("status"), "frozen_lifecycle_modified": False, "full_history_scan_count": 0},
        **SAFETY,
    }
