"""Bounded, read-only operational truth for Astra's existing paper lanes.

This module consolidates existing candidate, autopilot, broker-truth, and
lifecycle snapshots.  It never submits an order, persists a lifecycle, or
changes allocation.  Historical reconstruction is intentionally excluded from
current candidate and broker-truth counts.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from engine.astra_trade_lane_registry_v1 import LANE_CRYPTO, LANE_DAY, LANE_SWING, apply_trade_lane_contract, safety_fields
from engine.astra_paper_provider_cortex_completion_v1 import build_truth_acceleration_oversight
from engine.astra_multilane_activation_v2 import (
    adaptive_throughput,
    canonical_multilane_activation_contract,
    lane_capital_status,
    lane_handoff_proof,
    operational_freshness,
    strict_broker_truth,
    strict_truth_counts,
)


LANES = (LANE_SWING, LANE_DAY, LANE_CRYPTO)
MAX_DETAIL_ROWS = 25
COHORTS = ("SWING_EQUITY", "DAY_EQUITY", "DAY_ETF", "SWING_ETF", "CRYPTO")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_complete_broker_truth(row: Mapping[str, Any]) -> bool:
    """Require real complete broker evidence; reconstructions never qualify."""
    return strict_broker_truth(row)


def _is_current(candidate: Mapping[str, Any], freshness: str) -> bool:
    if freshness != "CURRENT":
        return False
    if bool(candidate.get("operational_probe_only")):
        return False
    evidence = _text(candidate.get("evidence_class") or candidate.get("truth_quality")).upper()
    return evidence not in {"MEDIUM_CONFIDENCE_RECONSTRUCTED", "AMBIGUOUS_REJECTED", "SHADOW", "REPLAY"}


def _cohort_id(row: Mapping[str, Any]) -> str:
    """Represent ETFs as cohorts within their canonical equity lanes."""
    lane = _text(row.get("lane_id")).upper()
    if lane == LANE_CRYPTO or _text(row.get("asset_class")).lower() == "crypto":
        return "CRYPTO"
    suffix = "ETF" if _text(row.get("instrument_type")).upper() == "ETF" else "EQUITY"
    return f"{lane}_{suffix}" if lane in {LANE_DAY, LANE_SWING} else "SWING_EQUITY"


def _truth_independence(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Weight strict truths by shared market context without discarding them."""
    strict_rows = [dict(row) for row in rows if isinstance(row, Mapping) and strict_broker_truth(row)]
    cluster_counts: Counter[str] = Counter()
    context_by_row: list[tuple[dict[str, Any], dict[str, str]]] = []
    for row in strict_rows:
        lane = _text(row.get("lane_id")).upper() or "UNKNOWN_LANE"
        strategy = _text(row.get("strategy_cohort") or row.get("strategy") or row.get("archetype")).upper() or "UNKNOWN_STRATEGY"
        symbol = _text(row.get("symbol")).upper() or "UNKNOWN_SYMBOL"
        sector = _text(row.get("sector") or row.get("sector_cluster") or (symbol if lane == LANE_CRYPTO else "UNKNOWN_SECTOR")).upper()
        regime = _text(row.get("market_regime") or row.get("regime") or "UNKNOWN_REGIME").upper()
        catalyst = _text(row.get("catalyst_id") or row.get("shared_catalyst") or "NO_SHARED_CATALYST").upper()
        entry = _text(row.get("entry_timestamp") or row.get("entry_time") or row.get("filled_at"))[:10] or "UNKNOWN_ENTRY_DAY"
        cluster = "|".join((lane, strategy, sector, regime, catalyst, entry))
        context = {
            "lane": lane, "strategy": strategy, "symbol": symbol, "sector_or_pair": sector,
            "regime": regime, "catalyst": catalyst, "entry_day": entry, "cluster": cluster,
        }
        cluster_counts[cluster] += 1
        context_by_row.append((row, context))
    contributions: list[dict[str, Any]] = []
    for row, context in context_by_row:
        cluster_size = cluster_counts[context["cluster"]]
        contributions.append({
            "truth_id": _text(row.get("truth_id") or row.get("lifecycle_id") or row.get("broker_order_id")),
            "symbol": context["symbol"],
            "lane": context["lane"],
            "raw_truth_weight": 1.0,
            "independence_weight": round(1.0 / max(1, cluster_size), 4),
            "correlation_cluster": context["sector_or_pair"],
            "shared_regime_cluster": context["regime"],
            "shared_strategy_cluster": context["strategy"],
            "quality_adjusted_truth_contribution": round(1.0 / max(1, cluster_size), 4),
        })
    return {
        "owner": "astra_multilane_operational_completion_v1._truth_independence",
        "raw_completed_broker_truths": len(strict_rows),
        "quality_adjusted_independent_truths": round(sum(row["quality_adjusted_truth_contribution"] for row in contributions), 4),
        "correlation_cluster_count": len(cluster_counts),
        "methodology": "strict broker truths are retained; simultaneous same lane/strategy/sector-or-pair/regime/catalyst/day clusters share unit evidence weight",
        "contributions": contributions[:MAX_DETAIL_ROWS],
        "shadow_replay_fixture_reconstructed_excluded": True,
    }


def _capacity_recycling_integrity(
    positions: Iterable[Mapping[str, Any]],
    reviews: Iterable[Mapping[str, Any]],
    capacity: Mapping[str, Any],
) -> dict[str, Any]:
    """Detect a confirmed closure that still consumes an authoritative slot."""
    open_symbols = {_text(row.get("symbol")).upper() for row in positions if _text(row.get("symbol"))}
    closed_symbols: set[str] = set()
    for row in reviews:
        reconciliation = _text(row.get("reconciliation_state")).upper()
        closure = _text(row.get("closure_state") or row.get("lifecycle_closure_state")).upper()
        broker_quantity = row.get("broker_position_quantity")
        broker_closed = broker_quantity in {0, 0.0, "0", "0.0"}
        if (reconciliation == "RECONCILED_CLOSED" or closure == "CLOSED_CONFIRMED") and broker_closed:
            symbol = _text(row.get("symbol")).upper()
            if symbol:
                closed_symbols.add(symbol)
    stale = sorted(symbol for symbol in closed_symbols if symbol in open_symbols)
    authority = _text(capacity.get("capacity_authority_state")).upper()
    return {
        "owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
        "confirmed_closed_symbols": sorted(closed_symbols),
        "open_symbols_still_counted": stale,
        "state": "REPAIRABLE_CAPACITY_DEFECT" if stale else "PASS" if authority == "CURRENT" else "WAITING_FOR_CURRENT_CAPACITY_AUTHORITY",
        "capacity_release_timing": "same_safe_cycle_or_next_bounded_worker_cycle",
        "replacement_reconsideration": "existing_candidates_only_after_current_capacity_and_all_gates_pass",
        "cash_hold_valid_outcome": True,
        "automatic_replacement_order": False,
    }


def _legacy_position_resolution_integrity(
    positions: Iterable[Mapping[str, Any]], capacity: Mapping[str, Any],
) -> dict[str, Any]:
    """Report the existing lifecycle overlay without authorizing migration.

    Unapproved legacy records are a legitimate waiting state.  They remain in
    total broker risk and cannot free a current-strategy slot until the
    canonical worker receives an explicit Governance approval reference.
    """
    rows = [dict(row) for row in positions if isinstance(row, Mapping)]
    legacy = [row for row in rows if _text(row.get("management_cohort")).upper() == "LEGACY_POSITION_RESOLUTION"]
    approved = [row for row in legacy if bool(row.get("active_slot_exclusion_approved"))]
    missing_owner = sorted(_text(row.get("symbol")).upper() for row in rows if not _text(row.get("lifecycle_owner")))
    missing_thesis = sorted(_text(row.get("symbol")).upper() for row in rows if not _text(row.get("current_thesis")))
    missing_review = sorted(_text(row.get("symbol")).upper() for row in rows if not _text(row.get("next_review_at")))
    state = "REPAIRABLE_LIFECYCLE_DEFECT" if (missing_owner or missing_thesis or missing_review) else "LEGACY_MIGRATION_AWAITING_GOVERNANCE" if legacy and not approved else "PASS"
    return {
        "owner": "engine.astra_unified_position_lifecycle_v1",
        "positions_processed": len(rows),
        "legacy_positions_proposed": len(legacy),
        "legacy_positions_approved": len(approved),
        "active_slot_exclusion_count": int(capacity.get("approved_legacy_slot_exclusion_count") or 0),
        "full_risk_inclusion_required": True,
        "full_risk_inclusion_confirmed": all(bool(row.get("full_risk_included")) for row in legacy),
        "no_new_legacy_entries": True,
        "automatic_migration_enabled": False,
        "automatic_exit_authorized": False,
        "missing_lifecycle_owner": missing_owner,
        "missing_current_thesis": missing_thesis,
        "missing_next_review": missing_review,
        "state": state,
        "legitimate_waiting_state": state == "LEGACY_MIGRATION_AWAITING_GOVERNANCE",
    }


def _information_utilization(truths: list[Mapping[str, Any]], trace_rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Report only observed consumption; unknown categories are never claimed learned."""
    categories = (
        "broker_truth", "historical_similarity", "symbol_behavior", "opportunity_cost", "replay", "shadow",
        "regime", "sector", "breadth", "catalyst", "lifecycle", "exit", "risk_envelope_calibration",
    )
    truth_ids = {
        _text(row.get("truth_id") or row.get("lifecycle_id") or row.get("broker_order_id"))
        for row in truths
    }
    consumed_truth_ids = {
        _text(row.get("learning_truth_id") or row.get("truth_id") or row.get("lifecycle_id"))
        for row in trace_rows
        if _text(row.get("learning_delivery_status")).upper() in {"DELIVERED", "ACKNOWLEDGED"}
        and _text(row.get("learning_truth_id") or row.get("truth_id") or row.get("lifecycle_id")) in truth_ids
    }
    acknowledged = len(consumed_truth_ids)
    observed = {
        "broker_truth": {"available": len(truths), "retrieved": len(truths), "consumed": acknowledged, "decisions_influenced": 0, "acknowledgements": acknowledged},
        "lifecycle": {"available": len(truths), "retrieved": len(truths), "consumed": acknowledged, "decisions_influenced": 0, "acknowledgements": acknowledged},
        "exit": {"available": len(truths), "retrieved": len(truths), "consumed": acknowledged, "decisions_influenced": 0, "acknowledgements": acknowledged},
    }
    rows = {}
    available_not_consumed = 0
    for category in categories:
        row = dict(observed.get(category) or {"available": 0, "retrieved": 0, "consumed": 0, "decisions_influenced": 0, "acknowledgements": 0})
        row["state"] = "CONSUMED" if row["consumed"] else "AVAILABLE_NOT_CONSUMED" if row["available"] else "NOT_REPORTED"
        row["last_meaningful_use"] = "worker_trace_learning_delivery" if row["acknowledgements"] else None
        available_not_consumed += int(row["available"] > row["consumed"])
        rows[category] = row
    return {
        "owner": "existing learning/Cortex consumers",
        "categories": rows,
        "available_not_consumed": available_not_consumed,
        "unused_evidence_not_presented_as_learned": True,
    }


def _parallel_lane_readiness(
    lanes: Mapping[str, Mapping[str, Any]], capacity: Mapping[str, Mapping[str, Any]], capacity_snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    """Classify serialization without treating a canonical account lock as a defect."""
    restrictions = [
        {
            "restriction_id": "paper_autopilot_cycle_lock",
            "canonical_owner": "PaperAutopilot._cycle_lock",
            "scope": "account_worker_mutation",
            "configured_value": 1,
            "current_usage": "one canonical worker cycle",
            "reason": "serialize broker reconciliation and order-idempotency state",
            "safety_purpose": "prevent duplicate worker and duplicate order mutation",
            "classification": "VALID_ACCOUNT_LEVEL_SAFETY_LIMIT",
            "blocks_independent_certified_lanes": False,
        },
        {
            "restriction_id": "paper_autopilot_max_new_positions_per_cycle",
            "canonical_owner": "PaperAutopilot.max_new_positions_per_cycle",
            "scope": "account_entry_rate",
            "configured_value": "existing configured bounded value",
            "current_usage": "worker trace only",
            "reason": "bounded paper-entry rate",
            "safety_purpose": "prevent burst submissions before reconciliation",
            "classification": "VALID_ACCOUNT_LEVEL_SAFETY_LIMIT",
            "blocks_independent_certified_lanes": False,
        },
        {
            "restriction_id": "lane_reserve_position_limit",
            "canonical_owner": "astra_evidence_accumulation_capacity_v1",
            "scope": "lane",
            "configured_value": "existing DAY/CRYPTO reserve configuration",
            "current_usage": "authoritative capacity snapshot",
            "reason": "separate approved evidence books",
            "safety_purpose": "lane capital and position isolation",
            "classification": "VALID_LANE_LIMIT",
            "blocks_independent_certified_lanes": False,
        },
        {
            "restriction_id": "symbol_duplicate_exposure",
            "canonical_owner": "candidate_capacity_decision",
            "scope": "symbol",
            "configured_value": "one position per symbol",
            "current_usage": "candidate gate",
            "reason": "duplicate exposure prevention",
            "safety_purpose": "one lifecycle and order lineage per symbol",
            "classification": "VALID_SYMBOL_LIMIT",
            "blocks_independent_certified_lanes": False,
        },
    ]
    certifications: dict[str, dict[str, Any]] = {}
    for cohort, lane_name in (
        ("SWING_EQUITY", "swing"), ("DAY_EQUITY", "day"), ("DAY_ETF", "day"),
        ("SWING_ETF", "swing"), ("CRYPTO", "crypto"),
    ):
        lane = dict(lanes.get(lane_name) or {})
        cap = dict(capacity.get(lane_name) or {})
        blockers = []
        capacity_full = False
        if cap.get("authority_state") != "CURRENT":
            blockers.append("CAPACITY_AUTHORITY_NOT_CURRENT")
        if lane_name == "swing":
            global_status = _text(capacity_snapshot.get("global_capacity_status")).upper()
            active_slot_status = _text(capacity_snapshot.get("active_strategy_slot_capacity_status")).upper()
            slot_exclusions = int(capacity_snapshot.get("approved_legacy_slot_exclusion_count") or 0)
            if slot_exclusions > 0 and active_slot_status == "AVAILABLE":
                pass
            elif global_status != "AVAILABLE":
                capacity_full = True
                blockers.append(global_status or "GLOBAL_CAPACITY_NOT_AVAILABLE")
        elif cap.get("arithmetic_consistency") != "PASS":
            blockers.append("CAPACITY_ARITHMETIC_NOT_VERIFIED")
        elif int(cap.get("available_capacity") or 0) <= 0:
            capacity_full = True
            blockers.append("LANE_CAPACITY_EXHAUSTED")
        if not bool(lane.get("execution_enabled")):
            blockers.extend(list((lane.get("activation_contract") or {}).get("exact_blockers") or ["LANE_EXECUTION_NOT_ADMITTED"]))
        structural_blockers = [
            item for item in blockers
            if item not in {"GLOBAL_CAPACITY_EXHAUSTED", "LANE_CAPACITY_EXHAUSTED"}
        ]
        certifications[cohort] = {
            "cohort": cohort,
            "canonical_lane": lane_name.upper(),
            "state": "BLOCKED_FAIL_CLOSED" if structural_blockers else "CERTIFIED_CAPACITY_FULL" if capacity_full else "CERTIFIED_BOUNDED",
            "current_capacity_state": cap.get("state"),
            "lane_identity_complete": bool(lane.get("lane_contract")),
            "risk_envelope_owner": "existing pretrade decision contract",
            "duplicate_order_protection": True,
            "one_lifecycle_per_candidate": True,
            "one_position_per_symbol": True,
            "capital_book_integrity": lane_name == "swing" or cap.get("arithmetic_consistency") == "PASS",
            "broker_reconciliation_current": cap.get("authority_state") == "CURRENT",
            "truth_persistence_health": True,
            "exact_blockers": list(dict.fromkeys(str(item) for item in blockers if item)),
        }
    return {
        "owner": "astra_multilane_operational_completion_v1._parallel_lane_readiness",
        "restrictions": restrictions,
        "certifications": certifications,
        "legacy_global_serialization_removed": False,
        "serialization_conclusion": "existing_worker_lock_and_entry_rate_are_valid_account_level_safety_limits; lane capacity is independently evaluated",
    }


def _trace_funnel(rows: Iterable[Mapping[str, Any]]) -> dict[str, int]:
    """Use only compact worker trace counters; absent stages remain zero."""
    counters = Counter()
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        counters["submission_attempted"] += int(bool(row.get("submission_attempted") or row.get("order_attempted")))
        counters["orders_submitted"] += int(_text(row.get("submission_result") or row.get("order_result")).lower() in {"submitted", "accepted"})
        counters["entry_fills"] += int(bool(_text(row.get("entry_fill_id"))))
        counters["active_positions"] += int(bool(_text(row.get("position_id"))))
        counters["exit_orders"] += int(bool(_text(row.get("exit_order_id"))))
        counters["exit_fills"] += int(bool(_text(row.get("exit_fill_id"))))
        counters["completed_lifecycles"] += int(bool(_text(row.get("entry_fill_id")) and _text(row.get("exit_fill_id"))))
        counters["truth_rows"] += int(_text(row.get("truth_status")).upper() == "BROKER_CONFIRMED_COMPLETE")
        counters["learning_acknowledged"] += int(_text(row.get("learning_delivery_status")).upper() in {"DELIVERED", "ACKNOWLEDGED"})
    return {key: int(counters[key]) for key in (
        "submission_attempted", "orders_submitted", "entry_fills", "active_positions",
        "exit_orders", "exit_fills", "completed_lifecycles", "truth_rows", "learning_acknowledged",
    )}


def _first_causal_blocker(
    *, rows: list[Mapping[str, Any]], activation: Mapping[str, Any], freshness: str,
    trace_funnel: Mapping[str, int], capacity: Mapping[str, Any], session_allowed: bool,
) -> dict[str, Any]:
    """Return one upstream blocker instead of a misleading list of symptoms."""
    current_rows = [row for row in rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"]
    if not current_rows:
        if freshness != "CURRENT":
            return {"code": "CANDIDATE_FRESHNESS_NOT_READY", "owner": "existing bounded candidate producer", "next_expected_stage": "fresh_candidate_snapshot"}
        if not session_allowed:
            return {"code": "MARKET_SESSION_NOT_ELIGIBLE", "owner": "existing market-session gate", "next_expected_stage": "eligible_candidate"}
        return {"code": "NO_CURRENT_MARKET_OPPORTUNITY", "owner": "existing ranking engine", "next_expected_stage": "fresh_candidate"}
    if not any(row.get("eligibility_state") == "ELIGIBLE" for row in current_rows):
        exact = next(
            (dict(row.get("first_failing_gate") or {}) for row in current_rows if dict(row.get("first_failing_gate") or {}).get("code")),
            {},
        )
        if exact and exact.get("code") not in {"PASS", "UNKNOWN_FAIL_CLOSED"}:
            return {
                "code": exact.get("code"),
                "detail": exact.get("input_value"),
                "owner": exact.get("owner") or "PaperAutopilot eligibility gate",
                "validity": exact.get("validity"),
                "next_expected_stage": "eligible_candidate",
            }
        blocker = next((_text(row.get("order_blocker")) for row in current_rows if _text(row.get("order_blocker"))), "REJECTED_BY_EXISTING_GATES")
        return {"code": "UNKNOWN_FAIL_CLOSED", "detail": blocker, "owner": "PaperAutopilot eligibility gate", "validity": "UNKNOWN_FAIL_CLOSED", "next_expected_stage": "eligible_candidate"}
    if not bool(activation.get("execution_enabled")):
        return {"code": "LANE_EXECUTION_NOT_ADMITTED", "owner": "existing governance and lane activation contract", "next_expected_stage": "admitted_lane"}
    if not bool(capacity.get("capital_configured", True)):
        return {"code": "CAPITAL_CONFIGURATION_NOT_READY", "owner": "existing lane capacity configuration", "next_expected_stage": "capacity_available"}
    if not any(row.get("selection_state") == "SELECTED" for row in current_rows):
        return {"code": "ELIGIBLE_WORK_NOT_SELECTED", "owner": "PaperAutopilot selection", "next_expected_stage": "selected_candidate"}
    if not any(row.get("order_readiness_state") == "ORDER_READY" for row in current_rows):
        return {"code": "ORDER_CONTRACT_NOT_READY", "owner": "PaperAutopilot order readiness", "next_expected_stage": "order_ready"}
    if not trace_funnel.get("submission_attempted"):
        return {"code": "ORDER_NOT_ATTEMPTED", "owner": "isolated PaperAutopilot worker", "next_expected_stage": "submission_attempt"}
    if not trace_funnel.get("orders_submitted"):
        return {"code": "BROKER_ORDER_NOT_ACCEPTED", "owner": "paper broker order acknowledgement", "next_expected_stage": "broker_ack"}
    if not trace_funnel.get("entry_fills"):
        return {"code": "ENTRY_FILL_PENDING", "owner": "paper broker fill reconciliation", "next_expected_stage": "entry_fill"}
    if not trace_funnel.get("completed_lifecycles"):
        return {"code": "LIFECYCLE_NOT_CLOSED", "owner": "existing lifecycle and exit owner", "next_expected_stage": "completed_lifecycle"}
    if not trace_funnel.get("truth_rows"):
        return {"code": "BROKER_TRUTH_NOT_COMPLETE", "owner": "existing broker truth reconciliation", "next_expected_stage": "strict_broker_truth"}
    if not trace_funnel.get("learning_acknowledged"):
        return {"code": "LEARNING_ACKNOWLEDGEMENT_PENDING", "owner": "existing learning/Cortex consumers", "next_expected_stage": "learning_acknowledged"}
    return {"code": "NO_BLOCKER", "owner": "none", "next_expected_stage": "continue_observation"}


def _lane_contract(lane: str, cohort: str) -> dict[str, Any]:
    """Explicit read-only ownership contract for the existing lane pipeline."""
    return {
        "cohort_id": cohort,
        "canonical_lane": lane,
        "asset_class": "crypto" if cohort == "CRYPTO" else "equity",
        "instrument_type": "ETF" if cohort.endswith("ETF") else "CRYPTO" if cohort == "CRYPTO" else "EQUITY",
        "candidate_producer": "existing ranking/top-buys cache",
        "candidate_freshness_owner": "existing cache and provider governor",
        "normalization_owner": "AstraTradeLaneRegistryV1",
        "eligibility_owner": "PaperAutopilot",
        "capacity_owner": "existing lane capacity and evidence accumulation owner",
        "decision_owner": "PaperAutopilot",
        "order_owner": "PaperAutopilot isolated worker",
        "broker_owner": "configured paper broker adapter",
        "position_owner": "broker reconciliation and canonical lifecycle",
        "exit_owner": "existing natural exit lifecycle owner",
        "truth_owner": "existing broker truth reconciliation",
        "learning_consumers": ["canonical lifecycle learning", "Cortex", "governance"],
        "etf_is_cohort_not_execution_lane": cohort.endswith("ETF"),
        "behavior_safe_to_apply": False,
    }


def _stage_row(candidate: Mapping[str, Any], trace: Mapping[str, Any], *, current: bool, pilot_enabled: bool, capital_configured: bool) -> dict[str, Any]:
    row = apply_trade_lane_contract(candidate, legacy=False)
    # The execution trace is the authoritative handoff after candidate
    # decoration.  Carry its stable lineage back into this bounded status view
    # when the source snapshot predates the identity repair.
    for key in (
        "candidate_id", "recommendation_id", "selection_id", "candidate_source",
        "candidate_generated_at", "source_snapshot_id", "position_owner", "exit_policy_owner",
    ):
        if not row.get(key) and trace.get(key):
            row[key] = trace.get(key)
    symbol = _text(row.get("symbol") or row.get("ticker")).upper()
    selected = bool(trace.get("selected"))
    # A PaperAutopilot selection occurs only after its own eligibility gates;
    # traces from older cycles do not always repeat an explicit allowed flag.
    allowed = bool(trace.get("allowed") or trace.get("eligible")) or selected or _text(trace.get("reason")).lower() in {"paper_eligible", "selected"}
    session = dict(trace.get("session_confirmation") or trace.get("session_diag") or {})
    order_ready = bool(trace.get("order_ready")) or bool(
        selected and session.get("paper_order_submission_allowed")
    )
    blocker = _text(
        trace.get("order_readiness_reason")
        or trace.get("decision_reason")
        or trace.get("reason")
        or trace.get("exact_blocker")
        or trace.get("final_blocker_reason")
    )
    if not current:
        blocker = "BLOCKED_STALE_CANDIDATE"
    elif not capital_configured and row.get("lane_id") in {LANE_DAY, LANE_CRYPTO}:
        blocker = "BLOCKED_CAPITAL"
    elif not pilot_enabled and row.get("lane_id") == LANE_DAY:
        blocker = "BLOCKED_PILOT_DISABLED"
    elif not trace and not blocker and not allowed:
        blocker = "BLOCKED_PIPELINE_UNWIRED"
    stage = "ORDER_READY" if order_ready else "SELECTED" if selected else "ELIGIBLE" if allowed else "REJECTED_BY_EXISTING_GATE" if trace else "CLASSIFIED"
    if blocker:
        stage = blocker
    attribution = dict(trace.get("eligibility_gate_attribution_v1") or {})
    if not attribution:
        attribution = {
            "schema": "astra_eligibility_gate_attribution_v1",
            "candidate_id": _text(row.get("candidate_id")),
            "symbol": symbol,
            "eligibility_result": "ELIGIBLE" if allowed else "REJECTED",
            "first_failing_gate": {
                "code": "PASS" if allowed else "UNKNOWN_FAIL_CLOSED",
                "owner": "PaperAutopilot" if allowed else "existing candidate/worker handoff",
                "input_value": "eligible" if allowed else blocker,
                "required_value": "existing gates pass",
                "validity": "PASS" if allowed else "UNKNOWN_FAIL_CLOSED",
            },
            "all_failing_gates": [],
        }
    return {
        "lane_id": row.get("lane_id"), "asset_class": row.get("asset_class"),
        "instrument_type": row.get("instrument_type"), "trade_style": row.get("trade_style"),
        "strategy_cohort": row.get("strategy_cohort"), "intended_horizon": row.get("intended_horizon"),
        "candidate_id": _text(row.get("candidate_id")), "recommendation_id": _text(row.get("recommendation_id")),
        "selection_id": _text(row.get("selection_id") or trace.get("selection_id")),
        "symbol": symbol, "candidate_source": _text(row.get("candidate_source") or row.get("source")),
        "candidate_generated_at": _text(row.get("candidate_generated_at") or trace.get("candidate_generated_at") or row.get("decision_timestamp")),
        "source_snapshot_id": _text(row.get("source_snapshot_id") or trace.get("source_snapshot_id")),
        "eligibility_state": "ELIGIBLE" if allowed else "NOT_ELIGIBLE",
        "eligibility_reason": _text(trace.get("reason")),
        "pretrade_decision_contract_missing_fields": list(trace.get("pretrade_decision_contract_missing_fields") or []),
        "pretrade_decision_contract_conflicts": list(trace.get("pretrade_decision_contract_conflicts") or []),
        "allocation_state": _text(row.get("allocation_state")) or "DIAGNOSTIC_ONLY",
        "allocation_reason": _text(row.get("allocation_reason")),
        "diversity_state": "BLOCKED" if "correlation" in blocker or "sector" in blocker else "NOT_BLOCKED",
        "diversity_reason": blocker if "correlation" in blocker or "sector" in blocker else "",
        "selection_state": "SELECTED" if selected else "NOT_SELECTED",
        "selection_reason": _text(trace.get("reason")),
        "selection_timestamp": _text(trace.get("selection_timestamp") or row.get("selection_timestamp")),
        "order_readiness_state": "ORDER_READY" if order_ready else "NOT_READY",
        "order_blocker": blocker, "operational_stage": stage,
        "eligibility_gate_attribution_v1": attribution,
        "first_failing_gate": dict(attribution.get("first_failing_gate") or {}),
        "same_session_exit_required": bool(row.get("same_session_exit_required")),
        "overnight_allowed": bool(row.get("overnight_allowed")),
        "capital_book_id": row.get("capital_book_id"),
        "position_owner": row.get("position_owner") or "",
        "exit_policy_owner": row.get("exit_policy_owner") or "",
    }


def build_multilane_operational_status(
    *,
    candidates: Iterable[Mapping[str, Any]],
    open_positions: Iterable[Mapping[str, Any]],
    broker_truth_records: Iterable[Mapping[str, Any]],
    autopilot_trace: Mapping[str, Any] | None = None,
    source_metadata: Mapping[str, Any] | None = None,
    day_config: Mapping[str, Any] | None = None,
    crypto_lane: Mapping[str, Any] | None = None,
    activation_contracts: Mapping[str, Mapping[str, Any]] | None = None,
    execution_ledger: Mapping[str, Any] | None = None,
    capacity_snapshot: Mapping[str, Any] | None = None,
    position_review_rows: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a cache-first status payload from existing authoritative owners."""
    trace_rows = list((autopilot_trace or {}).get("per_candidate_decision_trace") or [])
    trace_by_symbol = {_text(row.get("symbol")).upper(): dict(row) for row in trace_rows if isinstance(row, Mapping)}
    source_metadata = dict(source_metadata or {})
    day_config = dict(day_config or {})
    crypto_lane = dict(crypto_lane or {})
    activation_contracts = dict(activation_contracts or canonical_multilane_activation_contract())
    execution_ledger = dict(execution_ledger or {})
    capacity_snapshot = dict(capacity_snapshot or {})
    position_review_rows = [dict(row) for row in (position_review_rows or []) if isinstance(row, Mapping)]
    freshness_meta = operational_freshness(source_metadata.get("candidate_snapshot_age_seconds", source_metadata.get("candidate_cache_age_seconds")))
    freshness = _text(source_metadata.get("candidate_freshness_status") or freshness_meta["candidate_snapshot_freshness"]).upper() or "MISSING"
    current = [_stage_row(row, trace_by_symbol.get(_text(row.get("symbol") or row.get("ticker")).upper(), {}), current=_is_current(row, freshness), pilot_enabled=bool(day_config.get("day_lane_pilot_enabled")), capital_configured=bool(day_config.get("capital_configured"))) for row in candidates if isinstance(row, Mapping)]
    positions = [apply_trade_lane_contract(row, legacy=True) for row in open_positions if isinstance(row, Mapping)]
    truths = [apply_trade_lane_contract(row, legacy=True) for row in broker_truth_records if isinstance(row, Mapping) and _is_complete_broker_truth(row)]
    legacy_complete = [row for row in broker_truth_records if isinstance(row, Mapping) and _text(row.get("truth_quality")).upper() == "BROKER_CONFIRMED_COMPLETE"]
    lane_payloads: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        rows = [row for row in current if row.get("lane_id") == lane]
        lane_positions = [row for row in positions if row.get("lane_id") == lane]
        lane_truths = [row for row in truths if row.get("lane_id") == lane]
        blockers = Counter(_text(row.get("order_blocker")) for row in rows if _text(row.get("order_blocker")))
        capital = lane_capital_status(lane) if lane in {LANE_DAY, LANE_CRYPTO} else {
            "capital_configured": True, "capital_book_id": "paper_swing", "approved_ceiling": None,
            "configured_limit": None, "capital_in_use": 0.0, "capital_reserved": 0.0, "capital_available": None,
            "capital_configuration_status": "NOT_APPLICABLE",
        }
        activation = dict(activation_contracts.get(lane) or {})
        lane_freshness = freshness
        if lane == LANE_CRYPTO and not bool(crypto_lane.get("candidate_freshness_ready")):
            # Crypto has an independent 24/7 cache; an equity snapshot cannot
            # make a missing crypto ranking snapshot look current.
            lane_freshness = "MISSING"
        enabled = bool(activation.get("lane_enabled"))
        execution_enabled = bool(activation.get("execution_enabled"))
        handoff = lane_handoff_proof(
            lane,
            trace_rows,
            capital,
            session=source_metadata.get("market_session_status"),
        )
        lane_trace_rows = [row for row in trace_rows if _text(row.get("lane_id")).upper() == lane]
        trace_funnel = _trace_funnel(lane_trace_rows)
        throughput = adaptive_throughput(lane, truths)
        # A caller may supply the legacy shadow-only crypto mode without an
        # explicit canonical snapshot (notably deterministic tests and older
        # read-only consumers).  Preserve that truthful state rather than
        # letting ambient process configuration reinterpret it as paper-active.
        if lane == LANE_CRYPTO and crypto_lane.get("mode") and crypto_lane.get("paper_crypto_enabled") is False:
            status = "SHADOW_ONLY"
        elif lane == LANE_CRYPTO and not capital.get("capital_configured") and not crypto_lane.get("mode"):
            status = "CAPITAL_CONFIGURATION_REQUIRED"
        elif lane == LANE_CRYPTO and not enabled:
            status = (
                "SHADOW_ONLY"
                if crypto_lane.get("mode") or _text(crypto_lane.get("lane_state")).upper() == "LANE_SHADOW_ONLY"
                else
                "LANE_DISABLED"
                if crypto_lane.get("paper_account_crypto_support") or crypto_lane.get("broker_capability_available")
                else "BROKER_CAPABILITY_BLOCKED"
            )
        elif lane == LANE_DAY and not capital.get("capital_configured"):
            status = str(capital.get("capital_configuration_status") or "CAPITAL_CONFIGURATION_REQUIRED")
        elif lane == LANE_DAY and not enabled:
            status = "PILOT_DISABLED"
        elif handoff.get("market_session_trace_proven"):
            status = "MARKET_CLOSED"
        elif lane_freshness != "CURRENT":
            status = "STALE_CANDIDATES" if lane_freshness == "STALE" else "NO_CURRENT_SIGNAL"
        elif any(row.get("order_readiness_state") == "ORDER_READY" for row in rows):
            status = "ACTIVE" if enabled and handoff.get("proven") else "READY_FOR_ACTIVATION"
        else:
            status = "REJECTED_BY_EXISTING_GATE" if lane_trace_rows else "BLOCKED" if blockers else "NO_CURRENT_SIGNAL"
        lane_payloads[lane.lower()] = {
            "lane_id": lane, "lane_enabled": enabled, "execution_enabled": execution_enabled,
            "activation_contract": activation, "operational_status": status,
            "capital_configured": bool(capital.get("capital_configured")),
            "capital_book_id": capital.get("capital_book_id"),
            "approved_capital_ceiling": capital.get("approved_ceiling"),
            "configured_capital_limit": capital.get("configured_limit"),
            "capital_in_use": capital.get("capital_in_use"),
            "capital_reserved": capital.get("capital_reserved"),
            "capital_available": capital.get("capital_available"),
            "capital_configuration_status": capital.get("capital_configuration_status"),
            "adaptive_level": throughput.get("adaptive_level"),
            "max_open_positions_current": throughput.get("max_open_positions_current"),
            "max_open_positions_approved": throughput.get("max_open_positions_approved"),
            "max_completed_trades_current": throughput.get("max_completed_trades_current"),
            "max_completed_trades_approved": throughput.get("max_completed_trades_approved"),
            "clean_truths_for_next_level": throughput.get("clean_truths_for_next_level"),
            "next_level_requirements": "5 strict truths for Level 2; 20 strict truths for Level 3",
            "current_candidates": sum(1 for row in rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"),
            "eligible_candidates": sum(1 for row in rows if row.get("eligibility_state") == "ELIGIBLE"),
            "actual_selected_candidates": sum(1 for row in rows if row.get("selection_state") == "SELECTED"),
            "order_ready_candidates": sum(1 for row in rows if row.get("order_readiness_state") == "ORDER_READY"),
            "open_positions": len(lane_positions), "broker_truth_complete": len(lane_truths),
            "top_blockers": [name for name, _count in blockers.most_common(5)],
            "candidate_source": source_metadata.get("candidate_source") or "cached_top_buys_snapshot",
            "candidate_cache_generated_at": source_metadata.get("candidate_cache_generated_at"),
            "candidate_cache_age_seconds": source_metadata.get("candidate_cache_age_seconds"),
            "candidate_freshness": lane_freshness,
            "candidate_snapshot_age_seconds": freshness_meta.get("candidate_snapshot_age_seconds"),
            "candidate_snapshot_max_age_seconds": freshness_meta.get("candidate_snapshot_max_age_seconds"),
            "candidate_snapshot_freshness": lane_freshness,
            "authoritative_trace_count": len(lane_trace_rows),
            "autopilot_handoff_status": "MARKET_SESSION_TRACE_PROVEN" if handoff.get("market_session_trace_proven") else "DRY_RUN_PROVEN" if handoff.get("proven") else "TRACE_EXISTS_REJECTED" if lane_trace_rows else "HANDOFF_NOT_PROVEN",
            "autopilot_handoff_proof": handoff,
            "position_owner_status": "PASS" if all(row.get("position_owner") == lane for row in lane_positions) else "LANE_CONTRACT_REQUIRED",
            "exit_owner_status": "PASS" if all(row.get("exit_policy_owner") == lane for row in lane_positions) else "LANE_CONTRACT_REQUIRED",
            "learning_consumer_status": "CANONICAL_OUTCOME_ON_BROKER_TRUTH_COMPLETE",
            "first_causal_blocker": _first_causal_blocker(
                rows=rows, activation=activation, freshness=lane_freshness, trace_funnel=trace_funnel,
                capacity=capital, session_allowed=bool(activation.get("session_allowed", True)),
            ),
            "lifecycle_funnel": {
                "candidate_generated": len(rows),
                "fresh_candidate": sum(1 for row in rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"),
                "normalized": sum(1 for row in rows if _text(row.get("symbol"))),
                "eligible": sum(1 for row in rows if row.get("eligibility_state") == "ELIGIBLE"),
                "selected": sum(1 for row in rows if row.get("selection_state") == "SELECTED"),
                "order_ready": sum(1 for row in rows if row.get("order_readiness_state") == "ORDER_READY"),
                **trace_funnel,
                "broker_truth_complete": len(lane_truths),
            },
            "lane_contract": _lane_contract(lane, f"{lane}_EQUITY" if lane != LANE_CRYPTO else "CRYPTO"),
            "detailed_candidates": rows[:MAX_DETAIL_ROWS],
        }
    etf_rows = [row for row in current if row.get("instrument_type") == "ETF"]
    etf_positions = [row for row in positions if row.get("instrument_type") == "ETF"]
    etf_truths = [row for row in truths if row.get("instrument_type") == "ETF"]
    cohort_payloads: dict[str, dict[str, Any]] = {}
    ledger_windows = dict(execution_ledger.get("window") or {})
    ledger_cohorts = dict(ledger_windows.get("cohorts") or {})
    for cohort in COHORTS:
        cohort_rows = [row for row in current if _cohort_id(row) == cohort]
        cohort_positions = [row for row in positions if _cohort_id(row) == cohort]
        cohort_truths = [row for row in truths if _cohort_id(row) == cohort]
        canonical_lane = LANE_CRYPTO if cohort == "CRYPTO" else LANE_DAY if cohort.startswith("DAY") else LANE_SWING
        cohort_funnel = dict(ledger_cohorts.get(cohort) or {})
        cohort_payloads[cohort.lower()] = {
            "cohort_id": cohort, "canonical_lane": canonical_lane,
            "candidate_count": len(cohort_rows),
            "fresh_candidate_count": sum(1 for row in cohort_rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"),
            "eligible_count": sum(1 for row in cohort_rows if row.get("eligibility_state") == "ELIGIBLE"),
            "selected_count": sum(1 for row in cohort_rows if row.get("selection_state") == "SELECTED"),
            "open_positions": len(cohort_positions), "broker_truth_complete": len(cohort_truths),
            "rolling_trace_funnel": cohort_funnel,
            "rolling_trace_status": ledger_windows.get("history_status", "WARMING_UP"),
            "lane_contract": _lane_contract(canonical_lane, cohort),
        }
    lifecycle_lineage = {
        "active_positions": len(positions),
        "positions_with_lifecycle_id": sum(1 for row in positions if _text(row.get("lifecycle_id"))),
        "positions_with_entry_fill": sum(1 for row in positions if _text(row.get("entry_fill_id") or row.get("entry_order_fill_id"))),
        "completed_truth_records": len(truths),
        "strict_truth_requires_fill_pair": True,
        "review_rows_available": len(position_review_rows),
        "review_rows_missing": max(0, len(positions) - len(position_review_rows)),
        "dead_letter_owner": "existing continuous governance recovery campaigns",
        "dead_letter_mutation_on_get": False,
    }
    capacity_integrity: dict[str, dict[str, Any]] = {}
    capacity_lanes = dict(capacity_snapshot.get("lanes") or {})
    for lane in LANES:
        view = dict(capacity_lanes.get(lane.lower()) or {})
        used = view.get("positions_used")
        remaining = view.get("positions_remaining")
        configured = view.get("configured_position_limit")
        if configured is None and isinstance(used, (int, float)) and isinstance(remaining, (int, float)):
            configured = used + remaining
        reserve_state = _text(view.get("reserve_state") or view.get("capacity_status")) or "NOT_APPLICABLE"
        arithmetic = "UNKNOWN"
        if configured is not None and isinstance(used, (int, float)) and isinstance(remaining, (int, float)):
            arithmetic = "PASS" if int(configured) == int(used) + int(remaining) else "INCONSISTENT"
        capacity_integrity[lane.lower()] = {
            "configured_capacity": configured, "used_capacity": used,
            "pending_orders": view.get("pending_order_count"),
            "active_commitments": view.get("active_commitment_count"),
            "available_capacity": remaining, "reserve_state": reserve_state,
            "arithmetic_consistency": arithmetic,
            "authority_owner": view.get("capacity_authority_owner") or capacity_snapshot.get("capacity_authority_owner") or "PaperAutopilot._evidence_capacity_snapshot_v1",
            "authority_timestamp": view.get("capacity_authority_timestamp") or capacity_snapshot.get("capacity_authority_timestamp") or capacity_snapshot.get("generated_at"),
            "authority_state": view.get("capacity_authority_state") or capacity_snapshot.get("capacity_authority_state") or ("STALE" if "STALE" in reserve_state else "CURRENT"),
            "broker_positions_fetch_ok": bool(capacity_snapshot.get("broker_positions_fetch_ok")),
            "broker_positions_error_sanitized": str(capacity_snapshot.get("broker_positions_error_sanitized") or "")[:180],
            "state": "BROKER_UNREACHABLE" if (view.get("capacity_authority_state") or capacity_snapshot.get("capacity_authority_state")) == "BROKER_UNREACHABLE" else "STALE" if "STALE" in reserve_state else "INCONSISTENT" if arithmetic == "INCONSISTENT" else "PASS" if arithmetic == "PASS" else "WARMING_UP",
        }
    capacity_recycling = _capacity_recycling_integrity(positions, position_review_rows, capacity_snapshot)
    legacy_resolution = _legacy_position_resolution_integrity(positions, capacity_snapshot)
    governance_findings: list[dict[str, Any]] = []
    if capacity_recycling["state"] == "REPAIRABLE_CAPACITY_DEFECT":
        governance_findings.append({
            "code": "REPAIRABLE_CAPACITY_DEFECT",
            "severity": "HIGH",
            "owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
            "symbols": capacity_recycling["open_symbols_still_counted"],
            "safe_remediation": "reconcile_confirmed_broker_closure_then_refresh_existing_capacity_snapshot",
        })
    for lane_name, row in capacity_integrity.items():
        if row.get("arithmetic_consistency") == "INCONSISTENT":
            governance_findings.append({
                "code": "CAPACITY_ARITHMETIC_INCONSISTENT",
                "severity": "HIGH",
                "owner": row.get("authority_owner"),
                "lane": lane_name.upper(),
                "safe_remediation": "refresh_authoritative_broker_reconciliation_before_entry",
            })
    if legacy_resolution["state"] == "REPAIRABLE_LIFECYCLE_DEFECT":
        governance_findings.append({
            "code": "LEGACY_POSITION_LIFECYCLE_INCOMPLETE",
            "severity": "HIGH",
            "owner": legacy_resolution["owner"],
            "symbols": sorted(set(
                legacy_resolution["missing_lifecycle_owner"]
                + legacy_resolution["missing_current_thesis"]
                + legacy_resolution["missing_next_review"]
            )),
            "safe_remediation": "refresh_existing_unified_lifecycle_management_overlay_in_normal_worker_cycle",
        })
    truth_independence = _truth_independence(truths)
    information_utilization = _information_utilization(truths, trace_rows)
    parallel_lane_readiness = _parallel_lane_readiness(lane_payloads, capacity_integrity, capacity_snapshot)
    eligible_work = sum(int(view.get("eligible_candidates") or 0) for view in lane_payloads.values())
    current_work = sum(int(view.get("current_candidates") or 0) for view in lane_payloads.values())
    active_lifecycles = sum(int(view.get("open_positions") or 0) for view in lane_payloads.values())
    strict_truths = len(truths)
    if strict_truths:
        flat_truth_state = "BROKER_TRUTH_PRODUCING"
    elif active_lifecycles:
        flat_truth_state = "WAITING_FOR_ACTIVE_LIFECYCLE_EXIT"
    elif eligible_work:
        flat_truth_state = "ELIGIBLE_WORK_STALLED"
    elif current_work:
        flat_truth_state = "VALID_GATE_REJECTIONS"
    else:
        flat_truth_state = "NO_MARKET_OPPORTUNITY"
    scoreboard = {
        "today_status": ledger_windows.get("history_status", "WARMING_UP"),
        "rolling_window_days": ledger_windows.get("window_days", 0),
        "cohort_count": len(cohort_payloads),
        "strict_broker_truths": strict_truths,
        "completed_lifecycles": sum(int((row.get("rolling_trace_funnel") or {}).get("completed_lifecycles", 0) or 0) for row in cohort_payloads.values()),
        "learning_acknowledgements": sum(int((row.get("rolling_trace_funnel") or {}).get("learning_deliveries", 0) or 0) for row in cohort_payloads.values()),
        "official_metric_state": "WARMING_UP" if not truths else "STRICT_BROKER_TRUTH_AVAILABLE",
        "shadow_or_reconstructed_metrics_excluded": True,
        "flat_truth_escalation_state": flat_truth_state,
        "flat_truth_escalation_owner": "existing Governance and PaperAutopilot throughput owners",
        "flat_truth_requires_human_review": flat_truth_state in {"ELIGIBLE_WORK_STALLED", "CLOSURE_PIPELINE_STALLED", "TRUTH_PERSISTENCE_STALLED"},
        "raw_broker_truths": truth_independence["raw_completed_broker_truths"],
        "quality_adjusted_independent_truths": truth_independence["quality_adjusted_independent_truths"],
        "truth_independence_methodology": truth_independence["methodology"],
        "candidate_to_truth_conversion": round(strict_truths / max(1, current_work), 4),
        "truth_velocity_state": "WARMING_UP" if strict_truths < 5 else "OBSERVATIONAL",
    }
    cortex_oversight = build_truth_acceleration_oversight(
        lanes=lane_payloads,
        scoreboard=scoreboard,
        capacity_integrity=capacity_integrity,
        governance_findings=governance_findings,
        information_utilization=information_utilization,
        legacy_resolution=legacy_resolution,
    )
    all_lanes_enabled = all(bool(lane_payloads[key].get("lane_enabled")) for key in lane_payloads)
    operational_status = (
        "ASTRA_MULTILANE_OPERATIONAL_ENABLED"
        if all_lanes_enabled and all(lane_payloads[key]["operational_status"] != "PIPELINE_UNWIRED" for key in lane_payloads)
        else "ASTRA_MULTILANE_OPERATIONAL_PASS_WITH_HUMAN_CONFIGURATION_REQUIRED"
        if all(lane_payloads[key]["operational_status"] not in {"BROKER_CAPABILITY_UNAVAILABLE", "BROKER_CAPABILITY_BLOCKED", "PIPELINE_UNWIRED"} for key in lane_payloads)
        else "ASTRA_MULTILANE_OPERATIONAL_BLOCKED"
    )
    return {
        "endpoint": "/api/multilane_paper_operational_status_v1",
        "suite": "Astra Multi-Lane Paper Trading Operational Completion V1",
        "status": operational_status,
        "authoritative_owners": {
            "candidate_generation": "existing ranking/top-buys cache", "lane_classification": "AstraTradeLaneRegistryV1",
            "allocation": "PaperOpportunityAllocationEngineV1", "selection": "PaperAutopilot",
            "broker_truth": "existing truth-integrity registry", "reconstruction": "AstraHistoricalLifecycleReconstructionV1 (diagnostic only)",
        },
        "lanes": lane_payloads,
        "cohorts": cohort_payloads,
        "throughput_windows": ledger_windows,
        "capacity_snapshot": capacity_snapshot,
        "capacity_integrity": capacity_integrity,
        "lifecycle_lineage_integrity": lifecycle_lineage,
        "truth_production_scoreboard": scoreboard,
        "truth_independence": truth_independence,
        "parallel_lane_readiness": parallel_lane_readiness,
        "capacity_recycling_integrity": capacity_recycling,
        "legacy_position_resolution": legacy_resolution,
        "information_utilization": information_utilization,
        "cortex_truth_acceleration_oversight": cortex_oversight,
        "governance_truth_acceleration_findings": governance_findings,
        "day_selection_semantics": {
            "diagnostic_candidate_rows": len([row for row in current if row.get("lane_id") == LANE_DAY]),
            "actual_selection_owner": "PaperAutopilot.per_candidate_decision_trace.selected",
            "diagnostic_selection_is_not_actual_selection": True,
        },
        "etf_cohort": {
            "etf_current_candidates": sum(1 for row in etf_rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"),
            "etf_eligible_candidates": sum(1 for row in etf_rows if row.get("eligibility_state") == "ELIGIBLE"),
            "etf_selected_candidates": sum(1 for row in etf_rows if row.get("selection_state") == "SELECTED"),
            "etf_open_positions": len(etf_positions), "etf_broker_truth_complete": len(etf_truths),
            "etf_classification_health": "PASS" if all(row.get("asset_class") == "equity" for row in etf_rows + etf_positions + etf_truths) else "WARNING",
            "canonical_representation": {"asset_class": "equity", "instrument_type": "ETF", "is_lane": False},
        },
        "broker_truth_counts": {**strict_truth_counts(broker_truth_records), "legacy_broker_complete_diagnostic_count": len(legacy_complete)},
        "current_candidate_rows": current[:MAX_DETAIL_ROWS * len(LANES)],
        "simulation": {"supported": True, "submit_order": False, "broker_actions_used": 0, "fixture_truth_excluded_from_official_counts": True},
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
        "full_history_scan_count": 0, "human_review_required": True,
        **safety_fields(),
    }
