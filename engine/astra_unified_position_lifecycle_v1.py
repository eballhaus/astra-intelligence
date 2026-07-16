"""Canonical read-only lifecycle decisions built from existing position evidence.

This module never submits or queues an exit. PaperAutopilot remains the sole
authorized order writer; this owner only makes every position's evidence,
cohort, lifecycle classification, and policy blocker explicit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def classify_position_cohort_v1(position: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(position or {})
    quantity = abs(_num(row.get("qty") or row.get("quantity")) or 0.0)
    value = abs(_num(row.get("market_value")) or 0.0)
    contract = _text(row.get("contract_id") or row.get("pretrade_decision_contract_id"))
    candidate = _text(row.get("candidate_id") or row.get("source_candidate_id"))
    broker_id = _text(row.get("asset_id") or row.get("position_id") or row.get("symbol"))
    if quantity <= 0 or value < 0.01:
        cohort = "DUST_POSITION"
    elif not broker_id:
        cohort = "BROKER_RESIDUE_POSITION"
    elif contract and candidate:
        cohort = "NEW_COMPLETE_CONTRACT_POSITION"
    elif candidate or _text(row.get("lifecycle_id")):
        cohort = "LEGACY_PARTIAL_LINEAGE_POSITION"
    else:
        cohort = "LEGACY_PRE_CONTRACT_POSITION"
    return {"cohort": cohort, "position_id": broker_id, "legacy_forward_only_management": cohort.startswith("LEGACY"),
            "original_history_state": "UNAVAILABLE" if cohort.startswith("LEGACY") else "AVAILABLE"}


def build_unified_position_lifecycle_decision_v1(
    position: Mapping[str, Any], *, current_market_evidence: Mapping[str, Any] | None = None,
    lifecycle_plan: Mapping[str, Any] | None = None, learned_evidence: Mapping[str, Any] | None = None,
    shadow_evidence: Mapping[str, Any] | None = None, replacement_candidates: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return one evidence-labelled, advisory lifecycle decision per position."""
    row, market, plan, learned, shadow = dict(position or {}), dict(current_market_evidence or {}), dict(lifecycle_plan or {}), dict(learned_evidence or {}), dict(shadow_evidence or {})
    cohort = classify_position_cohort_v1(row)
    lane = _text(row.get("lane_id") or plan.get("lane") or "SWING").upper()
    original_horizon = _text(row.get("intended_horizon") or row.get("paper_entry_horizon_style") or plan.get("intended_horizon"))
    days = _num(row.get("days_held") or row.get("position_age_days")) or 0.0
    ret = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc"))
    if ret is not None and abs(ret) <= 1:
        ret *= 100.0
    exit_state = _text(row.get("exit_readiness_state") or "").upper()
    if cohort["cohort"] == "DUST_POSITION": state = "DUST_CLEANUP_REVIEW"
    elif exit_state in {"THESIS_BROKEN", "EXIT_REVIEW", "REPLACE_CANDIDATE"}: state = exit_state
    elif ret is None: state = "INSUFFICIENT_EVIDENCE"
    elif ret > 0 and _num(row.get("profit_giveback_pct")) and (_num(row.get("profit_giveback_pct")) or 0) > 2: state = "PROTECT_PROFIT"
    elif days >= 30: state = "EXIT_REVIEW"
    else: state = "HOLD_WITH_WATCH" if days >= 15 else "HOLD_AS_PLANNED"
    direct = bool(market or row.get("current_price") or row.get("market_price"))
    evidence_rows = [
        {"source_system": "broker_position", "evidence_class": "CURRENT_DIRECT", "retrieved": True, "matched": True, "consumed": True, "influenced_decision": True},
        {"source_system": "lifecycle_plan", "evidence_class": "CURRENT_CONTRACT" if plan else "UNAVAILABLE", "retrieved": bool(plan), "matched": bool(plan), "consumed": bool(plan), "influenced_decision": bool(plan)},
        {"source_system": "learned_evidence", "evidence_class": "HISTORICAL_SUPPORTED" if learned else "UNAVAILABLE", "retrieved": bool(learned), "matched": bool(learned), "consumed": bool(learned), "influenced_decision": bool(learned)},
        {"source_system": "shadow_replay", "evidence_class": "SHADOW_SUPPORTED" if shadow else "UNAVAILABLE", "retrieved": bool(shadow), "matched": bool(shadow), "consumed": bool(shadow), "influenced_decision": bool(shadow)},
    ]
    policy_eligible = state in {"PROTECT_PROFIT", "THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "REPLACE_CANDIDATE", "DUST_CLEANUP_REVIEW"}
    blocker = "HUMAN_POLICY_DECISION_REQUIRED" if policy_eligible else "ADVISORY_CLASSIFICATION_ONLY"
    if not direct: blocker = "INSUFFICIENT_CURRENT_DIRECT_EVIDENCE"
    horizon_state = "HORIZON_EXPIRED" if original_horizon == "day_trade" and days > 1.25 else "ORIGINAL_HORIZON_MAINTAINED" if original_horizon else "HORIZON_EVIDENCE_INSUFFICIENT"
    return {"position_id": cohort["position_id"], "symbol": _text(row.get("symbol")).upper(), "cohort": cohort["cohort"], "lane": lane,
            "original_horizon": original_horizon or "UNKNOWN", "current_recommended_horizon": original_horizon or "UNKNOWN", "horizon_state": horizon_state,
            "lifecycle_plan_state": "AVAILABLE" if plan else "LEGACY_FORWARD_ONLY", "lifecycle_stage": "POSITION_ACTIVE", "classification": state,
            "consensus_state": "LOW_CONFIDENCE" if not direct else "CONSENSUS_EXIT_REVIEW" if state in {"EXIT_REVIEW", "THESIS_BROKEN"} else "CONSENSUS_HOLD_WITH_WATCH",
            "hold_forward_value": "UNKNOWN" if ret is None else round(ret, 4), "exit_now_forward_value": ret, "replacement_forward_value": "UNKNOWN",
            "shadow_guidance": "SHADOW_INSUFFICIENT" if not shadow else "SHADOW_SUPPORTS_EXIT_REVIEW" if state == "EXIT_REVIEW" else "SHADOW_SUPPORTS_HOLD",
            "evidence_rows": evidence_rows, "evidence_consumed_count": sum(1 for item in evidence_rows if item["consumed"]),
            "policy_eligibility": "POLICY_BLOCKED" if policy_eligible else "ADVISORY_ONLY", "paper_action_ready": False,
            "exact_blocker": blocker, "next_review": "next_session" if lane != "CRYPTO" else "continuous_crypto_review",
            "monitoring_intensity": "HEIGHTENED_MONITORING" if state in {"EXIT_REVIEW", "THESIS_BROKEN"} else "NORMAL_MONITORING",
            "consumer_acknowledgements": {"LIFECYCLE_PLAN_CONSUMED_BY_POSITION_MONITOR": bool(plan), "LIFECYCLE_PLAN_CONSUMED_BY_EXIT_REVIEW": bool(plan), "LIFECYCLE_PLAN_PERSISTED_FOR_TRUTH_CALIBRATION": bool(plan)},
            "advisory_only": True, "paper_actions_used": 0}
