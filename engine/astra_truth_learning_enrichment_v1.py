"""Passive, deterministic annotations for completed strict broker truths.

These helpers run only after the existing strict-truth gate has accepted a
paired-fill, broker-zero lifecycle.  They do not participate in eligibility,
execution, ranking, sizing, or policy decisions.
"""
from __future__ import annotations

from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _direction(value: Any) -> str | None:
    raw = _text(value).upper()
    if raw in {"UP", "LONG", "BULLISH", "BUY"}:
        return "UP"
    if raw in {"DOWN", "SHORT", "BEARISH", "SELL"}:
        return "DOWN"
    return None


def _range_from_context(context: Mapping[str, Any]) -> dict[str, float] | None:
    nested = context.get("expected_return_range")
    if isinstance(nested, Mapping):
        low = _number(_first(nested, "low_pct", "low", "min_pct"))
        high = _number(_first(nested, "high_pct", "high", "max_pct"))
    else:
        low = _number(_first(context, "expected_return_low_pct", "expected_move_low"))
        high = _number(_first(context, "expected_return_high_pct", "expected_move_high"))
    midpoint = _number(_first(context, "expected_return_pct", "expected_move_percent"))
    if low is None and midpoint is not None:
        low = midpoint
    if high is None and midpoint is not None:
        high = midpoint
    if low is None and high is None:
        return None
    if low is None:
        low = high
    if high is None:
        high = low
    return {"low_pct": round(float(low), 6), "high_pct": round(float(high), 6)}


def build_pretrade_truth_context_v1(
    entry_payload: Mapping[str, Any] | None,
    entry_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Copy available entry evidence without deriving new predictions."""
    payload = dict(entry_payload or {})
    contract = dict(entry_contract or {})
    merged = {**payload, **{key: value for key, value in contract.items() if value not in (None, "", [], {})}}
    keys = (
        "predicted_direction", "direction", "trade_direction", "recommended_direction",
        "candidate_id", "recommendation_id", "selection_id", "lane_id", "horizon",
        "intended_horizon", "paper_entry_horizon_style", "expected_hold", "expected_hold_minutes",
        "maximum_hold_minutes", "maximum_hold_seconds", "expected_max_hold", "confidence",
        "predicted_win_probability", "expected_return_pct", "expected_return_low_pct",
        "expected_return_high_pct", "expected_move_percent", "expected_move_low", "expected_move_high",
        "thesis", "entry_rationale", "catalyst", "catalyst_type", "detected_catalyst",
        "market_regime", "regime_context", "expected_downside", "invalidation_conditions",
        "thesis_invalidation_conditions", "profit_objective", "expected_target_high", "target_1",
        "same_session_exit_required", "overnight_allowed", "weekend_allowed", "exit_conditions",
        "loss_thresholds", "entry_contract_id",
    )
    context = {key: merged[key] for key in keys if merged.get(key) not in (None, "", [], {})}
    expected_range = _range_from_context(merged)
    if expected_range is not None:
        context["expected_return_range"] = expected_range
    return context


def build_truth_learning_enrichment_v1(
    truth: Mapping[str, Any],
    *,
    pretrade_context: Mapping[str, Any] | None = None,
    lifecycle_notes: Mapping[str, Any] | None = None,
    learning_acknowledged: bool | None = None,
) -> dict[str, Any]:
    """Evaluate a completed truth strictly from persisted evidence.

    The return shape is deliberately observational.  ``UNAVAILABLE`` means no
    producer supplied that fact; it is never replaced by a retrospective
    inference.
    """
    record = dict(truth or {})
    context = dict(pretrade_context or record.get("pretrade_context_v1") or {})
    notes = dict(lifecycle_notes or {})
    actual_return = _number(record.get("realized_return"))
    if actual_return is None:
        actual_return = _number(record.get("return_percent"))
    actual_direction = "UNAVAILABLE"
    if actual_return is not None:
        actual_direction = "UP" if actual_return > 0 else ("DOWN" if actual_return < 0 else "FLAT")
    predicted_direction = _direction(_first(context, "predicted_direction", "direction", "trade_direction", "recommended_direction"))
    expected_range = _range_from_context(context)
    forecast_error = None
    within_expected_range = None
    if actual_return is not None and expected_range is not None:
        midpoint = (expected_range["low_pct"] + expected_range["high_pct"]) / 2.0
        forecast_error = round(actual_return - midpoint, 6)
        within_expected_range = expected_range["low_pct"] <= actual_return <= expected_range["high_pct"]

    max_hold_seconds = _number(_first(context, "maximum_hold_seconds", "expected_max_hold"))
    if max_hold_seconds is None:
        minutes = _number(_first(context, "maximum_hold_minutes", "expected_hold_minutes"))
        max_hold_seconds = minutes * 60.0 if minutes is not None else None
    hold_seconds = _number(record.get("hold_duration"))
    if hold_seconds is None:
        hold_seconds = _number(record.get("holding_period"))
    horizon_assessment = "UNAVAILABLE"
    if hold_seconds is not None and max_hold_seconds is not None and max_hold_seconds > 0:
        horizon_assessment = "WITHIN_MAX_HOLD" if hold_seconds <= max_hold_seconds else "BEYOND_MAX_HOLD"

    thesis_state = _text(_first(notes, "thesis_state", "current_thesis_state")).upper()
    thesis_outcome = "UNAVAILABLE"
    if thesis_state in {"FAILED", "BROKEN", "INVALIDATED"}:
        thesis_outcome = "FAILED"
    elif thesis_state in {"HELD", "VALID", "CONFIRMED"}:
        thesis_outcome = "HELD"
    momentum_state = _text(_first(notes, "momentum_state", "current_momentum_state")) or "UNAVAILABLE"
    mfe = _number(_first(record, "mfe", "max_favorable_excursion"))
    mae = _number(_first(record, "mae", "max_adverse_excursion"))
    giveback = _number(_first(record, "profit_giveback", "profit_giveback_pct"))
    if giveback is None:
        giveback = _number(_first(notes, "drawdown_from_peak_percent", "profit_giveback_pct"))

    learning_complete = bool(learning_acknowledged) if learning_acknowledged is not None else bool(record.get("learning_acknowledged"))
    provenance = _text(_first(record, "source_bucket", "ownership_status", "source")).upper()
    ambiguous = any(token in provenance for token in ("LEGACY", "RECONSTRUCT", "HISTORICAL", "SHADOW", "REPLAY"))
    components = {
        "canonical_lifecycle_identity": bool(_text(record.get("lifecycle_id"))),
        "broker_paired_entry_fill": bool(_text(record.get("entry_order_id")) and _text(record.get("entry_fill_id"))),
        "broker_paired_exit_fill": bool(_text(record.get("exit_order_id")) and _text(record.get("exit_fill_id"))),
        "broker_zero_confirmation": bool(record.get("broker_residual_zero_confirmed") or record.get("broker_zero_confirmed")),
        "broker_confirmed_closure": _text(record.get("evidence_class") or record.get("truth_quality")).upper() == "BROKER_CONFIRMED_COMPLETE",
        "entry_exit_timestamps": bool(_text(record.get("entry_time")) and _text(record.get("exit_time"))),
        "pretrade_context": bool(context),
        "exit_reason": bool(_text(record.get("exit_reason"))),
        "no_reconstruction_ambiguity": not ambiguous,
        "learning_acknowledged": learning_complete,
    }
    weights = {
        "canonical_lifecycle_identity": 15, "broker_paired_entry_fill": 15,
        "broker_paired_exit_fill": 15, "broker_zero_confirmation": 15,
        "broker_confirmed_closure": 15, "entry_exit_timestamps": 5,
        "pretrade_context": 8, "exit_reason": 5,
        "no_reconstruction_ambiguity": 5, "learning_acknowledged": 2,
    }
    score = sum(weights[key] for key, present in components.items() if present)
    if ambiguous:
        score = min(score, 25)
    grade = "A" if score >= 90 else ("B" if score >= 75 else ("C" if score >= 55 else "D"))
    missing = [key for key, present in components.items() if not present]

    return {
        "version": "1.0.0",
        "observational_only": True,
        "lifecycle_id": _text(record.get("lifecycle_id")),
        "prediction_accuracy_v1": {
            "predicted_direction": predicted_direction or "UNAVAILABLE",
            "predicted_horizon": _text(_first(context, "horizon", "intended_horizon", "paper_entry_horizon_style")) or "UNAVAILABLE",
            "expected_return_range": expected_range or "UNAVAILABLE",
            "confidence": _number(_first(context, "confidence", "predicted_win_probability")),
            "thesis": _text(_first(context, "thesis", "entry_rationale")) or "UNAVAILABLE",
            "catalyst": _text(_first(context, "catalyst", "catalyst_type", "detected_catalyst")) or "UNAVAILABLE",
            "expected_downside": _first(context, "expected_downside") or "UNAVAILABLE",
            "invalidation_condition": _first(context, "invalidation_conditions", "thesis_invalidation_conditions") or "UNAVAILABLE",
            "actual_direction": actual_direction,
            "actual_return_pct": actual_return,
            "actual_hold_seconds": hold_seconds,
            "direction_prediction_correct": (
                predicted_direction == actual_direction if predicted_direction and actual_direction in {"UP", "DOWN"} else "UNAVAILABLE"
            ),
            "forecast_error_pct_points": forecast_error if forecast_error is not None else "UNAVAILABLE",
            "within_expected_return_range": within_expected_range if within_expected_range is not None else "UNAVAILABLE",
            "horizon_assessment": horizon_assessment,
            "thesis_outcome": thesis_outcome,
        },
        "hold_quality_exit_timing_v1": {
            "hold_duration_seconds": hold_seconds,
            "maximum_hold_seconds": max_hold_seconds if max_hold_seconds is not None else "UNAVAILABLE",
            "hold_horizon_assessment": horizon_assessment,
            "maximum_favorable_excursion_pct": mfe if mfe is not None else "UNAVAILABLE",
            "maximum_adverse_excursion_pct": mae if mae is not None else "UNAVAILABLE",
            "profit_giveback_pct": giveback if giveback is not None else "UNAVAILABLE",
            "thesis_state_at_exit": thesis_state or "UNAVAILABLE",
            "momentum_state_at_exit": momentum_state,
            "opportunity_cost_state": _first(notes, "opportunity_cost_state", "opportunity_cost") or "UNAVAILABLE",
            "return_per_day": _first(notes, "return_per_day", "return_per_day_pct") or "UNAVAILABLE",
            "exit_timing_assessment": "UNAVAILABLE_WITHOUT_COUNTERFACTUAL_EVIDENCE",
        },
        "truth_quality_score_v1": {
            "score": score,
            "grade": grade,
            "components": components,
            "missing_or_unavailable": missing,
            "explanation": "Passive learning-confidence annotation; strict-truth eligibility is unchanged.",
        },
    }
