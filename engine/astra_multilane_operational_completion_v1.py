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
from engine.astra_multilane_activation_v2 import (
    adaptive_throughput,
    canonical_multilane_activation_contract,
    lane_capital_status,
    lane_handoff_proof,
    operational_freshness,
    strict_truth_counts,
)


LANES = (LANE_SWING, LANE_DAY, LANE_CRYPTO)
MAX_DETAIL_ROWS = 25
COHORTS = ("SWING_EQUITY", "DAY_EQUITY", "DAY_ETF", "SWING_ETF", "CRYPTO")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_complete_broker_truth(row: Mapping[str, Any]) -> bool:
    """Require real complete broker evidence; reconstructions never qualify."""
    evidence = _text(row.get("evidence_class") or row.get("truth_quality")).upper()
    if evidence != "BROKER_CONFIRMED_COMPLETE":
        return False
    return bool(
        _text(row.get("entry_fill_id") or row.get("entry_order_fill_id"))
        and _text(row.get("exit_fill_id") or row.get("exit_order_fill_id"))
    )


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
        blocker = next((_text(row.get("order_blocker")) for row in current_rows if _text(row.get("order_blocker"))), "REJECTED_BY_EXISTING_GATES")
        return {"code": "CANDIDATES_REJECTED_BY_VALID_GATES", "detail": blocker, "owner": "PaperAutopilot eligibility gate", "next_expected_stage": "eligible_candidate"}
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
        "allocation_state": _text(row.get("allocation_state")) or "DIAGNOSTIC_ONLY",
        "allocation_reason": _text(row.get("allocation_reason")),
        "diversity_state": "BLOCKED" if "correlation" in blocker or "sector" in blocker else "NOT_BLOCKED",
        "diversity_reason": blocker if "correlation" in blocker or "sector" in blocker else "",
        "selection_state": "SELECTED" if selected else "NOT_SELECTED",
        "selection_reason": _text(trace.get("reason")),
        "selection_timestamp": _text(trace.get("selection_timestamp") or row.get("selection_timestamp")),
        "order_readiness_state": "ORDER_READY" if order_ready else "NOT_READY",
        "order_blocker": blocker, "operational_stage": stage,
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
        configured = view.get("position_limit")
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
            "state": "STALE" if "STALE" in reserve_state else "INCONSISTENT" if arithmetic == "INCONSISTENT" else "PASS" if arithmetic == "PASS" else "WARMING_UP",
        }
    scoreboard = {
        "today_status": ledger_windows.get("history_status", "WARMING_UP"),
        "rolling_window_days": ledger_windows.get("window_days", 0),
        "cohort_count": len(cohort_payloads),
        "strict_broker_truths": len(truths),
        "completed_lifecycles": sum(int((row.get("rolling_trace_funnel") or {}).get("completed_lifecycles", 0) or 0) for row in cohort_payloads.values()),
        "learning_acknowledgements": sum(int((row.get("rolling_trace_funnel") or {}).get("learning_deliveries", 0) or 0) for row in cohort_payloads.values()),
        "official_metric_state": "WARMING_UP" if not truths else "STRICT_BROKER_TRUTH_AVAILABLE",
        "shadow_or_reconstructed_metrics_excluded": True,
    }
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
