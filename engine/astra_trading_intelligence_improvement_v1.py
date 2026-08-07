"""Read-only continuity layer for Astra's pretrade-to-learning intelligence.

This module deliberately reuses the existing pretrade certification, strict
broker truth, position advisory, exit readiness, and calibration artifacts.
It never creates a trade, changes a threshold, or reconstructs a prediction
after an outcome has occurred.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


VERSION = "1.0.0"
MAX_ROWS = 200
SAFETY = {
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "forced_trades_enabled": False,
    "forced_exits_enabled": False,
    "automatic_promotions_enabled": False,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
    "broker_actions_used": 0,
    "get_route_read_only": True,
    "state_mutations_from_get": 0,
}


def _read(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _num(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def _truth_return(row: Mapping[str, Any]) -> float | None:
    for key in ("realized_return", "realized_return_pct", "return_pct", "pnl_pct"):
        value = _num(row.get(key))
        if value is not None:
            return value
    return None


def _confidence_bucket(value: Any) -> str:
    score = _num(value)
    if score is None:
        return "UNAVAILABLE"
    if 0 < score <= 1:
        score *= 100
    if score >= 90:
        return "90_PLUS"
    if score >= 80:
        return "80_TO_89"
    if score >= 70:
        return "70_TO_79"
    if score >= 60:
        return "60_TO_69"
    if score >= 50:
        return "50_TO_59"
    return "BELOW_50"


def _original_prediction(row: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only entry-time fields persisted with the strict truth row."""
    context = row.get("pretrade_context_v1")
    context = dict(context) if isinstance(context, Mapping) else {}
    thesis = context.get("thesis") or context.get("entry_rationale")
    expected = context.get("expected_return_range") or context.get("expected_return_pct")
    direction = context.get("expected_direction") or context.get("direction")
    timestamp = context.get("thesis_timestamp") or context.get("created_at")
    return {
        "available": bool(thesis or expected not in (None, "") or direction),
        "thesis": thesis,
        "expected_return": _num(expected),
        "direction": str(direction or "").upper() or "UNAVAILABLE",
        "timestamp": timestamp or "UNAVAILABLE",
        "confidence": context.get("confidence") or context.get("predicted_win_probability"),
        "horizon": context.get("intended_horizon") or context.get("paper_entry_horizon_style") or row.get("lane_id") or "UNAVAILABLE",
    }


def _prediction_grades(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    grades: list[dict[str, Any]] = []
    buckets: dict[str, list[float]] = {}
    unavailable = 0
    for truth in rows[:MAX_ROWS]:
        prediction = _original_prediction(truth)
        actual = _truth_return(truth)
        if not prediction["available"] or actual is None:
            unavailable += 1
            grades.append({"lifecycle_id": truth.get("lifecycle_id"), "symbol": truth.get("symbol"), "status": "UNAVAILABLE", "reason": "ORIGINAL_PRETRADE_PREDICTION_OR_BROKER_RETURN_MISSING"})
            continue
        direction = prediction["direction"]
        direction_correct = None if direction == "UNAVAILABLE" else ((direction in {"LONG", "UP", "BUY"} and actual > 0) or (direction in {"SHORT", "DOWN", "SELL"} and actual < 0))
        expected = prediction["expected_return"]
        expected_error = abs(actual - expected) if expected is not None else None
        bucket = _confidence_bucket(prediction["confidence"])
        buckets.setdefault(bucket, []).append(actual)
        grades.append({
            "lifecycle_id": truth.get("lifecycle_id"), "symbol": truth.get("symbol"), "status": "GRADED",
            "direction_correct": direction_correct, "expected_return_error_pct": expected_error,
            "actual_return_pct": actual, "confidence_bucket": bucket,
            "lane": truth.get("lane_id") or "UNAVAILABLE", "horizon": prediction["horizon"],
        })
    graded = [row for row in grades if row["status"] == "GRADED"]
    direction_rows = [row for row in graded if row.get("direction_correct") is not None]
    calibration = {
        bucket: {"sample_size": len(values), "average_return_pct": round(sum(values) / len(values), 4) if values else None,
                 "status": "INSUFFICIENT_EVIDENCE" if len(values) < 10 else "OBSERVATIONAL"}
        for bucket, values in sorted(buckets.items())
    }
    return grades, {
        "strict_truth_count": len(rows), "graded_prediction_count": len(graded), "unavailable_prediction_count": unavailable,
        "direction_accuracy_pct": round(100 * sum(bool(row["direction_correct"]) for row in direction_rows) / len(direction_rows), 3) if direction_rows else "UNAVAILABLE",
        "confidence_buckets": calibration,
        "promotion_allowed": False,
        "status": "INSUFFICIENT_EVIDENCE" if not graded else "OBSERVATIONAL_ONLY",
    }


def _hold_summary(advisory: Mapping[str, Any], readiness: Mapping[str, Any]) -> dict[str, Any]:
    readiness_by_symbol = {str(row.get("symbol") or "").upper(): row for row in readiness.get("positions") or [] if isinstance(row, dict)}
    rows = []
    for item in list(advisory.get("positions") or [])[:MAX_ROWS]:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        exit_row = readiness_by_symbol.get(symbol, {})
        recommendation = str(exit_row.get("recommendation") or item.get("final_advisory") or "WATCH").upper()
        thesis = str((item.get("evidence_used") or {}).get("thesis_state") or "ORIGINAL_THESIS_UNAVAILABLE").upper()
        rows.append({"symbol": symbol, "lifecycle_id": item.get("lifecycle_id"), "thesis_state": thesis,
                     "hold_state": recommendation, "momentum": (item.get("evidence_used") or {}).get("momentum_state", "UNAVAILABLE"),
                     "first_causal_blocker": exit_row.get("first_causal_blocker") or item.get("first_causal_blocker") or "UNAVAILABLE",
                     "execution_authority": "DISABLED"})
    return {"positions_monitored": len(rows), "states": rows, "canonical_exit_authority": "EXISTING_NATIVE_LIFECYCLE_ONLY",
            "automatic_exit_authority": False, "status": "OBSERVATIONAL" if rows else "UNAVAILABLE"}


def build_trading_intelligence_improvement_suite_v1(state_dir: str = "state") -> dict[str, Any]:
    """Build the bounded, cache-only intelligence loop from canonical state."""
    state = Path(state_dir)
    truth_registry = _read(state / "broker_truth_records_v1.json")
    advisory = _read(state / "astra_unified_position_advisory_v1.json")
    readiness = _read(state / "astra_position_exit_readiness_v1.json")
    worker = _read(state / "paper_autopilot_state.json")
    strict_truths = [
        dict(row) for row in (truth_registry.get("records") or [])
        if isinstance(row, dict) and str(row.get("truth_state") or "").upper()
        in {"STRICT_TRUTH", "BROKER_TRUTH_CONFIRMED", "BROKER_CONFIRMED_COMPLETE", "COMPLETE"}
    ]
    grades, calibration = _prediction_grades(strict_truths)
    holds = _hold_summary(advisory, readiness)
    exit_rows = holds["states"]
    counts = {name: sum(1 for row in exit_rows if row.get("hold_state") == name) for name in ("HOLD", "WATCH", "PROTECT_PROFIT", "EXIT_REVIEW", "REPLACE_CANDIDATE", "THESIS_BROKEN")}
    return {
        "suite": "ASTRA Trading Intelligence Improvement Suite V1", "version": VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "status": "OBSERVATIONAL_READY" if strict_truths or exit_rows else "INSUFFICIENT_EVIDENCE",
        "pre_market": {"owner": "astra_pre_market_trading_certification_v1", "status": "CACHE_FIRST_EXISTING_CERTIFICATION",
                        "session_plan_source": "existing canonical pretrade certification; dashboard GET does not refresh providers",
                        "order_authority": "EXISTING_CANONICAL_ENTRY_GATES_ONLY"},
        "post_market": {"strict_truth_count": len(strict_truths), "prediction_grading": calibration,
                        "lesson_status": "UNAVAILABLE" if not strict_truths else "BROKER_TRUTH_BACKED"},
        "pretrade_thesis": {"owner": "astra_premarket_certification_v1.build_pretrade_decision_contract",
                            "immutable_original_required": True, "missing_original_prediction_status": "UNAVAILABLE"},
        "hold_monitoring": holds,
        "prediction_grades": grades, "confidence_calibration": calibration,
        "momentum_exit_loss_acceptance": {"owner": "astra_profit_protection_giveback_v1 + astra_position_exit_readiness_v1",
                                            "advisory_state_counts": counts, "existing_loss_containment_authoritative": True,
                                            "automatic_exit_authority": False},
        "worker_identity": {key: worker.get(key) for key in ("worker_generation_id", "worker_cycle_count", "worker_heartbeat_at")},
        "integration_warnings": ["ORIGINAL_PRETRADE_PREDICTION_UNAVAILABLE" for _ in range(calibration["unavailable_prediction_count"])][:10],
        **SAFETY,
    }
