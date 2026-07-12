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


LANES = (LANE_SWING, LANE_DAY, LANE_CRYPTO)
MAX_DETAIL_ROWS = 25


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
    evidence = _text(candidate.get("evidence_class") or candidate.get("truth_quality")).upper()
    return evidence not in {"MEDIUM_CONFIDENCE_RECONSTRUCTED", "AMBIGUOUS_REJECTED", "SHADOW", "REPLAY"}


def _stage_row(candidate: Mapping[str, Any], trace: Mapping[str, Any], *, current: bool, pilot_enabled: bool, capital_configured: bool) -> dict[str, Any]:
    row = apply_trade_lane_contract(candidate, legacy=False)
    symbol = _text(row.get("symbol") or row.get("ticker")).upper()
    selected = bool(trace.get("selected"))
    # A PaperAutopilot selection occurs only after its own eligibility gates;
    # traces from older cycles do not always repeat an explicit allowed flag.
    allowed = bool(trace.get("allowed")) or selected or _text(trace.get("reason")).lower() in {"paper_eligible", "selected"}
    session = dict(trace.get("session_confirmation") or trace.get("session_diag") or {})
    order_ready = bool(trace.get("order_ready")) or bool(
        selected and session.get("paper_order_submission_allowed")
    )
    blocker = _text(trace.get("reason") or trace.get("exact_blocker") or trace.get("final_blocker_reason"))
    if not current:
        blocker = "BLOCKED_STALE_CANDIDATE"
    elif not capital_configured and row.get("lane_id") in {LANE_DAY, LANE_CRYPTO}:
        blocker = "BLOCKED_CAPITAL"
    elif not pilot_enabled and row.get("lane_id") == LANE_DAY:
        blocker = "BLOCKED_PILOT_DISABLED"
    elif not blocker and not allowed:
        blocker = "BLOCKED_PIPELINE_UNWIRED"
    stage = "ORDER_READY" if order_ready else "SELECTED" if selected else "ELIGIBLE" if allowed else "CLASSIFIED"
    if blocker:
        stage = blocker
    return {
        "lane_id": row.get("lane_id"), "asset_class": row.get("asset_class"),
        "instrument_type": row.get("instrument_type"), "trade_style": row.get("trade_style"),
        "strategy_cohort": row.get("strategy_cohort"), "intended_horizon": row.get("intended_horizon"),
        "candidate_id": _text(row.get("candidate_id")), "recommendation_id": _text(row.get("recommendation_id")),
        "symbol": symbol, "candidate_source": _text(row.get("candidate_source") or row.get("source")),
        "candidate_generated_at": _text(row.get("decision_timestamp")),
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
) -> dict[str, Any]:
    """Build a cache-first status payload from existing authoritative owners."""
    trace_rows = list((autopilot_trace or {}).get("per_candidate_decision_trace") or [])
    trace_by_symbol = {_text(row.get("symbol")).upper(): dict(row) for row in trace_rows if isinstance(row, Mapping)}
    source_metadata = dict(source_metadata or {})
    day_config = dict(day_config or {})
    crypto_lane = dict(crypto_lane or {})
    freshness = _text(source_metadata.get("candidate_freshness_status")).upper() or "MISSING"
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
        enabled = bool(crypto_lane.get("paper_crypto_enabled")) if lane == LANE_CRYPTO else bool(day_config.get("day_lane_pilot_enabled")) if lane == LANE_DAY else True
        if lane == LANE_CRYPTO and not crypto_lane.get("capital_configured", enabled) and not crypto_lane.get("mode"):
            status = "CAPITAL_CONFIGURATION_REQUIRED"
        elif lane == LANE_CRYPTO and not enabled:
            status = "SHADOW_ONLY" if _text(crypto_lane.get("lane_state")).upper() == "LANE_SHADOW_ONLY" or crypto_lane.get("mode") else "BROKER_CAPABILITY_UNAVAILABLE"
        elif lane == LANE_DAY and not day_config.get("capital_configured"):
            status = "CAPITAL_CONFIGURATION_REQUIRED"
        elif lane == LANE_DAY and not enabled:
            status = "PILOT_DISABLED"
        elif freshness != "CURRENT":
            status = "STALE_CANDIDATES" if freshness == "STALE" else "NO_CURRENT_SIGNAL"
        elif any(row.get("order_readiness_state") == "ORDER_READY" for row in rows):
            status = "READY_FOR_HUMAN_APPROVAL"
        else:
            status = "BLOCKED" if blockers else "NO_CURRENT_SIGNAL"
        lane_payloads[lane.lower()] = {
            "lane_id": lane, "lane_enabled": enabled, "operational_status": status,
            "capital_configured": bool(day_config.get("capital_configured")) if lane == LANE_DAY else bool(crypto_lane.get("capital_configured", enabled)) if lane == LANE_CRYPTO else True,
            "capital_book_id": "paper_day_learning" if lane == LANE_DAY else "paper_crypto_separate" if lane == LANE_CRYPTO else "paper_swing",
            "current_candidates": sum(1 for row in rows if row.get("operational_stage") != "BLOCKED_STALE_CANDIDATE"),
            "eligible_candidates": sum(1 for row in rows if row.get("eligibility_state") == "ELIGIBLE"),
            "actual_selected_candidates": sum(1 for row in rows if row.get("selection_state") == "SELECTED"),
            "order_ready_candidates": sum(1 for row in rows if row.get("order_readiness_state") == "ORDER_READY"),
            "open_positions": len(lane_positions), "broker_truth_complete": len(lane_truths),
            "top_blockers": [name for name, _count in blockers.most_common(5)],
            "candidate_source": source_metadata.get("candidate_source") or "cached_top_buys_snapshot",
            "candidate_cache_generated_at": source_metadata.get("candidate_cache_generated_at"),
            "candidate_cache_age_seconds": source_metadata.get("candidate_cache_age_seconds"),
            "candidate_freshness": freshness,
            "autopilot_handoff_status": "DRY_RUN_PROVEN" if any(row.get("order_readiness_state") == "ORDER_READY" for row in rows) else "NOT_PROVEN_FROM_CURRENT_CANDIDATE",
            "position_owner_status": "LANE_CONTRACT_REQUIRED", "exit_owner_status": "LANE_CONTRACT_REQUIRED",
            "learning_consumer_status": "CANONICAL_OUTCOME_ON_BROKER_TRUTH_COMPLETE",
            "detailed_candidates": rows[:MAX_DETAIL_ROWS],
        }
    etf_rows = [row for row in current if row.get("instrument_type") == "ETF"]
    etf_positions = [row for row in positions if row.get("instrument_type") == "ETF"]
    etf_truths = [row for row in truths if row.get("instrument_type") == "ETF"]
    return {
        "endpoint": "/api/multilane_paper_operational_status_v1",
        "suite": "Astra Multi-Lane Paper Trading Operational Completion V1",
        "status": "ASTRA_MULTILANE_OPERATIONAL_PASS_WITH_HUMAN_CONFIGURATION_REQUIRED" if all(lane_payloads[key]["operational_status"] not in {"BROKER_CAPABILITY_UNAVAILABLE", "PIPELINE_UNWIRED"} for key in lane_payloads) else "ASTRA_MULTILANE_OPERATIONAL_BLOCKED",
        "authoritative_owners": {
            "candidate_generation": "existing ranking/top-buys cache", "lane_classification": "AstraTradeLaneRegistryV1",
            "allocation": "PaperOpportunityAllocationEngineV1", "selection": "PaperAutopilot",
            "broker_truth": "existing truth-integrity registry", "reconstruction": "AstraHistoricalLifecycleReconstructionV1 (diagnostic only)",
        },
        "lanes": lane_payloads,
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
        "broker_truth_counts": {
            "total_broker_confirmed_complete": len(truths),
            "swing_broker_confirmed_complete": len([row for row in truths if row.get("lane_id") == LANE_SWING]),
            "day_broker_confirmed_complete": len([row for row in truths if row.get("lane_id") == LANE_DAY]),
            "crypto_broker_confirmed_complete": len([row for row in truths if row.get("lane_id") == LANE_CRYPTO]),
            "equity_broker_confirmed_complete": len([row for row in truths if row.get("asset_class") == "equity"]),
            "etf_broker_confirmed_complete": len(etf_truths),
            "legacy_broker_complete_diagnostic_count": len(legacy_complete),
            "strict_fill_linked_truth_required": True,
            "cohort_counts_overlap_total": True,
        },
        "current_candidate_rows": current[:MAX_DETAIL_ROWS * len(LANES)],
        "simulation": {"supported": True, "submit_order": False, "broker_actions_used": 0, "fixture_truth_excluded_from_official_counts": True},
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
        "full_history_scan_count": 0, "human_review_required": True,
        **safety_fields(),
    }
