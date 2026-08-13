"""Read-only trade-learning evidence, lane participation, and calibration view.

This composes existing V5/V6, Warehouse, lane-ledger, and Operating Health
owners.  It neither persists evidence nor changes trade or adaptation policy.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
from engine.astra_operating_health_contract_v1 import AstraOperatingHealthContractV1
from engine.astra_trading_intelligence_improvement_v2 import _metrics, _number, _read, _return, _strict_truths
from engine.astra_trading_intelligence_improvement_v5 import _completeness, _ledger, _provenance
from engine.astra_trading_intelligence_improvement_v6 import (
    MAX_MATCHES,
    _context,
    _expected_hold_seconds,
    _expected_upside,
    _hold_duration,
    _prediction_error,
    _risk_reward,
    _similarity,
)
from engine.lane_execution_trace_ledger_v1 import LANES, LaneExecutionTraceLedgerV1


VERSION = "1.0.0"
MAX_TRADES = 100
SAFETY = {
    "read_only_derived_view": True,
    "provider_calls_added": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
    "execution_behavior_changed": False,
    "ranking_behavior_changed": False,
    "thresholds_changed": False,
    "automatic_promotion_authority": False,
    "frozen_lifecycle_modified": False,
    "full_history_scan_count": 0,
}


def _text(value: Any) -> str:
    return str(value or "").strip() or "UNAVAILABLE"


def _availability(value: Any) -> Any:
    return value if value not in (None, "", [], {}) else "UNAVAILABLE"


def _lane(row: Mapping[str, Any]) -> str:
    return _text(row.get("lane") or row.get("lane_id")).upper()


def _truth_id(row: Mapping[str, Any]) -> str:
    return _text(row.get("truth_id") or row.get("stable_key") or row.get("lifecycle_id"))


def _entry_context(row: Mapping[str, Any], context: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": _availability(context.get("candidate_id") or row.get("candidate_id")),
        "lane": _availability(context.get("lane") or context.get("lane_id") or row.get("lane") or row.get("lane_id")),
        "horizon": _availability(context.get("intended_horizon") or context.get("paper_entry_horizon_style") or row.get("horizon")),
        "entry_timestamp": _availability(row.get("entry_timestamp") or row.get("entry_fill_timestamp")),
        "entry_thesis": _availability(context.get("thesis") or context.get("entry_rationale")),
        "confidence": _availability(context.get("confidence") or context.get("predicted_win_probability")),
        "ranking_factors": _availability(context.get("ranking_factors")),
        "regime": _availability(context.get("market_regime") or context.get("regime")),
        "catalyst": _availability(context.get("catalyst") or context.get("catalyst_state")),
        "expected_hold_seconds": _availability(_expected_hold_seconds(context)),
        "expected_upside_pct": _availability(_expected_upside(context)),
        "expected_downside_pct": _availability(context.get("expected_downside")),
        "risk_envelope": _availability(context.get("risk_envelope") or context.get("candidate_risk_envelope_v1")),
        "quantity": _availability(row.get("entry_quantity") or row.get("quantity")),
        "capital": _availability(row.get("entry_notional") or context.get("capital_allocated")),
        "alternatives": _availability(context.get("alternatives") or context.get("opportunity_cost_context")),
    }


def _diagnostic_classification(row: Mapping[str, Any], prediction: Mapping[str, Any], hold: Mapping[str, Any], risk: Mapping[str, Any]) -> str:
    actual = _return(row)
    exit_reason = _text(row.get("exit_reason") or row.get("exit_policy"))
    if actual is None:
        return "UNAVAILABLE"
    if "THESIS" in exit_reason:
        return "THESIS_FAILED"
    if "MOMENTUM" in exit_reason:
        return "MOMENTUM_DETERIORATION"
    if "OPPORTUNITY" in exit_reason:
        return "OPPORTUNITY_COST"
    if actual > 0 and hold.get("status") == "HOLD_DURATION_ALIGNED":
        return "GOOD_ENTRY_GOOD_EXIT"
    if actual > 0 and hold.get("status") in {"HELD_TOO_LONG", "HORIZON_MISMATCH_SUSPECTED"}:
        return "GOOD_ENTRY_POOR_EXIT"
    if actual <= 0 and risk.get("status") == "RISK_REWARD_ALIGNED":
        return "NORMAL_VALID_LOSS"
    if actual <= 0 and "RISK_UNDERESTIMATED" not in (prediction.get("errors") or []):
        return "POOR_ENTRY_GOOD_LOSS_CONTROL"
    return "UNAVAILABLE"


def _handoff_by_lifecycle(health: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("lifecycle_id")): dict(item)
        for item in (health.get("truth_to_learning_ledger") or [])
        if isinstance(item, Mapping) and item.get("lifecycle_id")
    }


def _trade_evidence(row: Mapping[str, Any], handoffs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    context = _context(row)
    prediction, hold, risk = _prediction_error(row), _hold_duration(row), _risk_reward(row)
    handoff = dict(handoffs.get(str(row.get("lifecycle_id"))) or {})
    return {
        "evidence_record_id": f"trade_evidence:{_truth_id(row)}",
        "immutable_source": "canonical_strict_truth_and_pretrade_context",
        "lifecycle_id": _availability(row.get("lifecycle_id")),
        "candidate_id": _availability(context.get("candidate_id") or row.get("candidate_id")),
        "truth_id": _truth_id(row),
        "lesson_id": _availability(row.get("lesson_id")),
        "symbol": _availability(row.get("symbol")),
        "broker_evidence_class": _availability(row.get("evidence_class") or row.get("truth_quality")),
        "entry": _entry_context(row, context),
        "hold": {
            "mfe": _availability(row.get("mfe")), "mae": _availability(row.get("mae")),
            "time_profitable": _availability(row.get("time_profitable")), "time_losing": _availability(row.get("time_losing")),
            "momentum_changes": _availability(row.get("momentum_changes")), "thesis_changes": _availability(row.get("thesis_changes")),
            "regime_changes": _availability(row.get("regime_changes")), "opportunity_cost_changes": _availability(row.get("opportunity_cost_changes")),
            "hold_quality": hold,
        },
        "exit": {
            "reason": _availability(row.get("exit_reason") or row.get("exit_policy")), "exit_fill_id": _availability(row.get("exit_fill_id")),
            "exit_timestamp": _availability(row.get("exit_timestamp") or row.get("exit_fill_timestamp")), "realized_return_pct": _availability(_return(row)),
            "hold_duration_seconds": _availability(row.get("hold_duration")), "capture_ratio": _availability(row.get("capture_ratio")),
            "profit_giveback": _availability(row.get("profit_giveback")), "risk_reward": risk,
        },
        "learning_provenance": {
            "truth_linkage": _truth_id(row), "canonical_lesson_linkage": _availability(row.get("lesson_id")),
            "teacher_memory_cortex_handoff": _availability(handoff.get("stages")), "handoff_final_state": _availability(handoff.get("final_state")),
            "warehouse_owner": "AstraKnowledgeWarehouseV1", "compression_owner": "Knowledge Compression Engine V1", "teacher_owner": "Teacher Layer V1", "cortex_owner": "Existing Cortex",
        },
        "prediction_vs_reality": _calibration(row, prediction, hold, risk),
        "diagnostic_classification": _diagnostic_classification(row, prediction, hold, risk),
        "provenance_completeness": _provenance(row), "evidence_completeness": _completeness(row), "evidence_ledger": _ledger(row),
        "observational_only": True,
    }


def _proving_coverage(evidence: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Temporary bounded verification counters; no source rescan is required."""
    return {
        "mode": "BOUNDED_PROVING_PHASE",
        "records_checked": len(evidence),
        "original_prediction_verified": sum(item.get("provenance_completeness", {}).get("state") == "ORIGINAL_CAPTURE_VERIFIED" for item in evidence),
        "entry_thesis_available": sum(item.get("entry", {}).get("entry_thesis") != "UNAVAILABLE" for item in evidence),
        "excursion_available": sum(item.get("hold", {}).get("mfe") != "UNAVAILABLE" or item.get("hold", {}).get("mae") != "UNAVAILABLE" for item in evidence),
        "exit_reason_available": sum(item.get("exit", {}).get("reason") != "UNAVAILABLE" for item in evidence),
        "teacher_memory_cortex_handoff_observed": sum(item.get("learning_provenance", {}).get("teacher_memory_cortex_handoff") != "UNAVAILABLE" for item in evidence),
        "normal_consumer": "compressed/indexed canonical lessons; raw evidence remains drill-down only",
    }


def _calibration(row: Mapping[str, Any], prediction: Mapping[str, Any], hold: Mapping[str, Any], risk: Mapping[str, Any]) -> dict[str, Any]:
    context = _context(row)
    expected_return, actual_return = _expected_upside(context), _return(row)
    expected_hold, actual_hold = _expected_hold_seconds(context), _number(row.get("hold_duration"))
    expected_downside, actual_mae = _number(context.get("expected_downside")), _number(row.get("mae"))
    return {
        "status": prediction.get("status"), "prediction_errors": prediction.get("errors"),
        "expected_return_pct": _availability(expected_return), "actual_return_pct": _availability(actual_return),
        "return_error_pct": _availability(round(actual_return - expected_return, 5) if actual_return is not None and expected_return is not None else None),
        "expected_hold_seconds": _availability(expected_hold), "actual_hold_seconds": _availability(actual_hold),
        "hold_error_seconds": _availability(round(actual_hold - expected_hold, 5) if actual_hold is not None and expected_hold is not None else None),
        "expected_downside_pct": _availability(expected_downside), "actual_mae": _availability(actual_mae),
        "downside_error_pct": _availability(round(abs(actual_mae) - abs(expected_downside), 5) if actual_mae is not None and expected_downside is not None else None),
        "expected_opportunity_pct": _availability(expected_return), "actual_mfe": _availability(row.get("mfe")),
        "risk_reward_observation": risk, "hold_observation": hold,
    }


def _last_day_with(lane: Mapping[str, Any], daily: Mapping[str, Any], metric: str) -> str:
    return next((day for day in sorted(daily, reverse=True) if int((((daily.get(day) or {}).get("lanes") or {}).get(lane) or {}).get(metric) or 0) > 0), "UNAVAILABLE")


def _days_since(day: str) -> int | str:
    if day == "UNAVAILABLE":
        return "UNAVAILABLE"
    try:
        return max(0, (datetime.now(timezone.utc).date() - date.fromisoformat(day)).days)
    except ValueError:
        return "UNAVAILABLE"


def _lane_monitor(state_dir: str, truths: list[dict[str, Any],], health: Mapping[str, Any]) -> dict[str, Any]:
    summary = LaneExecutionTraceLedgerV1(state_dir).summary()
    daily, health_lanes = summary.get("daily_buckets") or {}, health.get("lanes") or {}
    rows = {}
    for lane in LANES:
        funnel = dict((summary.get("lanes") or {}).get(lane) or {})
        health_row = dict(health_lanes.get(lane) or {})
        top = dict(funnel.get("top_blockers") or {})
        current_blocker = _text(health_row.get("first_causal_blocker"))
        historical_blocker = max(top, key=top.get) if top else "UNAVAILABLE"
        blocker = current_blocker if current_blocker != "UNAVAILABLE" else historical_blocker
        if health_row.get("blocker_validity") == "UNCLASSIFIED_FAIL_CLOSED":
            state = "SOFTWARE_BLOCKER"
        elif current_blocker != "UNAVAILABLE" and ("BLOCK" in current_blocker or "RISK" in current_blocker or "CAPACITY" in current_blocker):
            state = "SAFETY_BLOCKED"
        elif funnel.get("order_ready", 0):
            state = "EXECUTION_READY"
        elif funnel.get("fresh_candidates", 0) == 0 and funnel.get("stale_candidates", 0):
            state = "DATA_STALE"
        elif funnel.get("candidates_seen", 0):
            state = "NO_VALID_OPPORTUNITY"
        else:
            state = "NORMAL_WAITING"
        lane_truths = [row for row in truths if _lane(row) == lane]
        entry_day, truth_day = _last_day_with(lane, daily, "filled_entries"), _last_day_with(lane, daily, "strict_broker_truths")
        rows[lane] = {
            "lane": lane, "funnel": {"candidates": int(funnel.get("candidates_seen") or 0), "eligible": int(funnel.get("eligible") or 0), "selected": int(funnel.get("selected") or 0), "order_ready": int(funnel.get("order_ready") or 0), "submitted": int(funnel.get("submitted") or 0), "filled": int(funnel.get("filled_entries") or 0), "exited": int(funnel.get("filled_exits") or 0), "strict_truth": len(lane_truths), "canonical_lesson": int(health_row.get("truths_consumed_by_learning") or 0)},
            "first_or_current_blocker": blocker, "historical_top_blocker": historical_blocker,
            "freshness": "STALE" if state == "DATA_STALE" else "FRESH_OR_UNOBSERVED",
            "participation_state": state, "last_natural_entry_date": entry_day, "days_since_last_natural_entry": _days_since(entry_day),
            "last_strict_truth_date": truth_day, "days_since_last_strict_truth": _days_since(truth_day), "completed_truth_count": len(lane_truths),
            "can_force_trade": False, "can_change_thresholds": False,
        }
    return {"owner": "LaneExecutionTraceLedgerV1 + AstraOperatingHealthContractV1", "lanes": rows, "authority": "observational_only_no_governance_override"}


def build_trade_learning_evidence_lane_monitor_v1(state_dir: str = "state", query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return a bounded derived view; normal invocation performs no writes."""
    state = Path(state_dir)
    truths = _strict_truths(_read(state / "broker_truth_records_v1.json"))[:MAX_TRADES]
    health = AstraOperatingHealthContractV1(state).snapshot()
    warehouse = AstraKnowledgeWarehouseV1(state_dir=str(state))
    handoffs = _handoff_by_lifecycle(health)
    evidence = [_trade_evidence(row, handoffs) for row in truths]
    query = dict(query or {})
    comparisons = []
    for row in truths[:MAX_MATCHES]:
        context = _context(row)
        similar_query = {"symbol": row.get("symbol"), "horizon": context.get("intended_horizon") or row.get("horizon"), "regime": context.get("market_regime") or context.get("regime"), "archetype": context.get("strategy_archetype"), "catalyst": context.get("catalyst")}
        warehouse_query = {key: value for key, value in similar_query.items() if key in {"symbol", "horizon", "regime", "archetype", "catalyst"} and value not in (None, "")}
        warehouse_result = warehouse.query({**warehouse_query, "max_results": MAX_MATCHES, "detail_level": "summary"})
        similar = _similarity(truths, {}, similar_query)
        comparisons.append({"lifecycle_id": row.get("lifecycle_id"), "truth_id": _truth_id(row), "similar_trade_comparison": similar, "warehouse_index_first_retrieval": {"index_used": warehouse_result.get("index_used"), "partitions_or_stores_used": warehouse_result.get("partitions_or_stores_used"), "raw_records_read": warehouse_result.get("raw_records_read"), "full_history_scan_used": warehouse_result.get("full_history_scan_used")}})
    return {
        "suite": "ASTRA Trade Learning Evidence + Lane Monitor + Prediction Calibration V1", "version": VERSION,
        "status": "OBSERVATIONAL_READY" if truths else "INSUFFICIENT_EVIDENCE", "strict_truth_count": len(truths),
        "complete_trade_evidence": {"owner": "canonical strict truth + V5 provenance/completeness", "records": evidence, "record_count": len(evidence), "immutable_source_records": True},
        "proving_phase_coverage": _proving_coverage(evidence),
        "lane_evidence_participation_monitor": _lane_monitor(str(state), truths, health),
        "prediction_vs_reality": {"owner": "V6 prediction/hold/risk calculations", "records": [{"lifecycle_id": item["lifecycle_id"], "truth_id": item["truth_id"], "calibration": item["prediction_vs_reality"]} for item in evidence]},
        "similar_trade_learning": {"owner": "V6 bounded similarity + Warehouse manifest/index-first retrieval", "comparisons": comparisons, "maximum_comparisons": MAX_MATCHES, "automatic_promotion_disabled": True},
        "learning_funnel": {"Cortex_insight_to_lifecycle": "lesson_id -> truth_id -> lifecycle_id -> canonical evidence record", "teacher_memory_owner": "existing Teacher/Memory", "compression_owner": "existing Librarian/Knowledge Compression Engine", "cortex_owner": "existing Cortex", "heavy_verification": "bounded MAX_TRADES/MAX_MATCHES proving view only"},
        **SAFETY,
    }
