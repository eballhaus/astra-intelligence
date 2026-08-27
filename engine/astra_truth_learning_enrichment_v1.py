"""Passive, deterministic annotations for completed strict broker truths.

These helpers run only after the existing strict-truth gate has accepted a
paired-fill, broker-zero lifecycle.  They do not participate in eligibility,
execution, ranking, sizing, or policy decisions.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Mapping


def _text(value: Any) -> str:
    return str(value or "").strip()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def merge_passive_excursion_evidence_v1(
    existing: Mapping[str, Any] | None,
    *,
    current_return_pct: float,
    current_price: float,
    observed_at: str,
    hold_seconds: float,
) -> dict[str, Any]:
    """Monotonically retain observed excursion facts without inventing bars.

    This is passive lifecycle evidence only. It records the observed quote path
    and never changes an exit, risk, or broker decision.
    """
    prior = dict(existing or {})
    old_mfe = _number(_first(prior, "max_favorable_excursion_pct", "max_favorable_excursion"))
    old_mae = _number(_first(prior, "max_adverse_excursion_pct", "max_adverse_excursion"))
    mfe = max(old_mfe, current_return_pct) if old_mfe is not None else current_return_pct
    mae = min(old_mae, current_return_pct) if old_mae is not None else current_return_pct
    peak_advanced = old_mfe is None or current_return_pct > old_mfe
    trough_advanced = old_mae is None or current_return_pct < old_mae
    count = int(_number(prior.get("excursion_observation_count")) or 0) + 1
    return {
        **prior,
        "max_favorable_excursion_pct": round(mfe, 6),
        "max_adverse_excursion_pct": round(mae, 6),
        "max_favorable_excursion": round(mfe, 6),
        "max_adverse_excursion": round(mae, 6),
        "peak_price": current_price if peak_advanced else prior.get("peak_price"),
        "trough_price": current_price if trough_advanced else prior.get("trough_price"),
        "time_to_peak": round(hold_seconds, 3) if peak_advanced else prior.get("time_to_peak"),
        "time_to_trough": round(hold_seconds, 3) if trough_advanced else prior.get("time_to_trough"),
        "profit_giveback_pct": round(max(0.0, mfe - current_return_pct), 6),
        "excursion_observation_count": count,
        "first_excursion_observation_at": prior.get("first_excursion_observation_at") or observed_at,
        "last_excursion_observation_at": observed_at,
        "excursion_evidence_source": "observed_paper_position_quote",
    }


def build_pretrade_truth_context_v1(
    entry_payload: Mapping[str, Any] | None,
    entry_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Copy available entry evidence without deriving new predictions."""
    payload = dict(entry_payload or {})
    contract = dict(entry_contract or {})
    frozen = contract.get("original_pretrade_prediction_snapshot_v1")
    if isinstance(frozen, Mapping) and bool(frozen.get("immutable_original_pretrade_prediction")):
        context = frozen.get("prediction_context")
        if isinstance(context, Mapping):
            # A completed truth must read the approved, pre-broker values, not
            # a later position/monitoring row that may have evolved in flight.
            return deepcopy(dict(context))
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
        # Passive provenance copied from existing certification context only.
        "contract_id", "decision_id", "asset_class", "symbol", "lane", "strategy_archetype",
        "trade_style", "expected_hold_window", "ranking_score", "ranking_factors",
        "thesis_supporting_conditions", "regime_fit", "sector_fit", "catalyst_state",
        "fundamental_state", "momentum_state", "liquidity_state", "risk_envelope",
        "candidate_risk_envelope_v1", "expected_outcome_envelope_v1", "field_provenance_v1",
        "source_inputs", "source_provenance", "certification_snapshot_id", "observation_timestamp",
        "market_data_timestamp", "forecast_timestamp", "valid_until", "factor_contributions",
        "evidence_factors", "confidence_attribution",
        "trend_state", "volume_state", "volatility_context", "supporting_evidence",
        "opposing_evidence", "evidence_freshness", "expected_exit_behavior",
        # Explicit producer quality states remain immutable pre-entry facts.
        # They enable later selection-vs-management attribution without using
        # realized P/L or any post-entry observation as an entry proxy.
        "entry_quality_state", "selection_quality_state", "candidate_quality_state",
        "qualification_state", "buy_eligibility", "pretrade_decision_contract_state",
    )
    # Preserve original pre-decision evidence as an immutable snapshot. Nested
    # attribution maps remain owned by their producers after entry processing.
    context = {key: deepcopy(merged[key]) for key in keys if merged.get(key) not in (None, "", [], {})}
    expected_range = _range_from_context(merged)
    if expected_range is not None:
        context["expected_return_range"] = expected_range
    return context


def build_original_pretrade_prediction_snapshot_v1(
    entry_payload: Mapping[str, Any] | None,
    entry_contract: Mapping[str, Any] | None,
    *,
    lifecycle_id: str,
    intended_entry_price: float | None = None,
    captured_at: str | None = None,
) -> dict[str, Any]:
    """Freeze only producer-supplied approved-entry evidence before a broker call."""
    payload, contract = dict(entry_payload or {}), dict(entry_contract or {})
    context = build_pretrade_truth_context_v1(payload, contract)
    candidate_id = context.get("candidate_id") or contract.get("candidate_id") or payload.get("candidate_id")
    lane = context.get("lane_id") or context.get("lane") or contract.get("lane") or payload.get("lane_id")
    horizon = context.get("intended_horizon") or context.get("paper_entry_horizon_style") or contract.get("horizon") or payload.get("horizon")
    return {
        "schema_version": "astra_original_pretrade_prediction_snapshot_v1",
        "snapshot_id": f"pretrade:{lifecycle_id}",
        "lifecycle_id": lifecycle_id or None,
        "candidate_id": candidate_id or None,
        "symbol": context.get("symbol") or contract.get("symbol") or payload.get("symbol") or None,
        "lane": lane or None,
        "horizon": horizon or None,
        "prediction_context": deepcopy(context),
        "intended_entry_price": intended_entry_price if intended_entry_price not in (None, 0) else None,
        "capital": payload.get("capital_allocated") or payload.get("notional") or payload.get("allocation") or None,
        "quantity": payload.get("quantity") or payload.get("qty") or None,
        "risk_envelope": context.get("risk_envelope") or context.get("candidate_risk_envelope_v1") or None,
        "captured_at": captured_at or _utc_now_iso(),
        "source_owner": "PaperAutopilotEngine._submit_alpaca_paper_entry_order",
        "immutable_original_pretrade_prediction": True,
        "snapshot_state": "APPROVED_NOT_SUBMITTED",
        "missing_values_are_unavailable": True,
    }


def build_pretrade_entry_quality_assessment_v1(
    pretrade_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Classify entry quality from immutable producer evidence only.

    This deliberately does not inspect realized return, excursion, or an exit
    outcome.  An absent explicit selection assessment is reported as
    insufficient evidence rather than reverse-engineered from a small cohort.
    """
    context = dict(pretrade_context or {})
    fields = (
        "entry_quality_state", "selection_quality_state", "candidate_quality_state",
        "qualification_state", "buy_eligibility", "pretrade_decision_contract_state",
    )
    observed = [(key, _text(context.get(key)).upper()) for key in fields if _text(context.get(key))]
    positive = {"GOOD", "STRONG", "QUALIFIED", "APPROVED", "PASS", "VALID", "ELIGIBLE", "BUY_NOW"}
    negative = {"POOR", "WEAK", "REJECTED", "FAILED", "INVALID", "INELIGIBLE", "BLOCKED"}
    for key, value in observed:
        if value in negative:
            return {
                "classification": "POOR_ENTRY", "status": "PRETRADE_EVIDENCE_AVAILABLE",
                "evidence_field": key, "evidence_value": value,
                "lookahead_safe": True,
            }
    for key, value in observed:
        if value in positive:
            return {
                "classification": "GOOD_ENTRY", "status": "PRETRADE_EVIDENCE_AVAILABLE",
                "evidence_field": key, "evidence_value": value,
                "lookahead_safe": True,
            }
    return {
        "classification": "INSUFFICIENT_EVIDENCE", "status": "PRETRADE_EXPLICIT_QUALITY_UNAVAILABLE",
        "evidence_field": None, "evidence_value": None, "lookahead_safe": True,
    }


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
    exit_decision_events = [
        dict(item) for item in list(record.get("exit_decision_evidence_v1") or [])
        if isinstance(item, Mapping)
    ]
    latest_exit_decision = exit_decision_events[-1] if exit_decision_events else {}
    mfe = _number(_first(record, "mfe", "max_favorable_excursion"))
    mae = _number(_first(record, "mae", "max_adverse_excursion"))
    giveback = _number(_first(record, "profit_giveback", "profit_giveback_pct"))
    if giveback is None:
        giveback = _number(_first(notes, "drawdown_from_peak_percent", "profit_giveback_pct"))
    capture_ratio = None
    if mfe is not None and mfe > 0 and actual_return is not None:
        capture_ratio = max(0.0, actual_return) / mfe
    realized_return_per_hour = (
        round(actual_return / (hold_seconds / 3600.0), 6)
        if actual_return is not None and hold_seconds is not None and hold_seconds >= 60.0
        else None
    )
    advisory_return = _number(_first(latest_exit_decision, "current_return_percent", "current_return_pct", "return_percent"))
    advisory_timestamp = _first(latest_exit_decision, "observed_at", "timestamp", "created_at")
    exit_advisory = {
        "status": "CAPTURED_PRE_ACTION" if latest_exit_decision else "INSUFFICIENT_EVIDENCE",
        "lifecycle_id": _text(record.get("lifecycle_id")) or "UNAVAILABLE",
        "event_timestamp": advisory_timestamp or "UNAVAILABLE",
        "available_return_at_advisory_pct": advisory_return if advisory_return is not None else "UNAVAILABLE",
        "event": dict(latest_exit_decision) if latest_exit_decision else "UNAVAILABLE",
        "actual_realized_return_pct": actual_return if actual_return is not None else "UNAVAILABLE",
        "actual_vs_advisory_return_delta_pct_points": (
            round(actual_return - advisory_return, 6)
            if actual_return is not None and advisory_return is not None else "UNAVAILABLE"
        ),
        "counterfactual_evidence_class": "OBSERVATIONAL_COUNTERFACTUAL_NOT_BROKER_TRUTH",
        "counterfactual_is_official_broker_truth": False,
    }

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
            # Captured pre-action decision evidence is observational only. It
            # records the exit owner's actual inputs without promoting a
            # later broker result into the historical management decision.
            "exit_decision_consumption_status": (
                "CAPTURED_PRE_ACTION" if latest_exit_decision else "UNAVAILABLE_HISTORICAL_OR_NOT_MATERIAL"
            ),
            "exit_decision_evidence_count": len(exit_decision_events),
            "last_exit_owner_decision": dict(latest_exit_decision.get("exit_owner_decision") or {}) or "UNAVAILABLE",
        },
        "profit_retention_v1": {
            "status": "AVAILABLE" if actual_return is not None and mfe is not None else "INSUFFICIENT_EVIDENCE",
            "realized_return_pct": actual_return if actual_return is not None else "UNAVAILABLE",
            "maximum_favorable_excursion_pct": mfe if mfe is not None else "UNAVAILABLE",
            "maximum_adverse_excursion_pct": mae if mae is not None else "UNAVAILABLE",
            "profit_capture_ratio": round(capture_ratio, 6) if capture_ratio is not None else "UNAVAILABLE",
            "profit_capture_pct": round(capture_ratio * 100.0, 6) if capture_ratio is not None else "UNAVAILABLE",
            "absolute_giveback_pct_points": giveback if giveback is not None else "UNAVAILABLE",
            "hold_duration_seconds": hold_seconds if hold_seconds is not None else "UNAVAILABLE",
            "return_per_hour": realized_return_per_hour if realized_return_per_hour is not None else "UNAVAILABLE",
            "expected_horizon": _text(_first(context, "horizon", "intended_horizon", "paper_entry_horizon_style")) or "UNAVAILABLE",
            "horizon_exceedance": horizon_assessment,
            "units": {"returns": "percentage_points", "profit_capture": "percent_of_mfe", "giveback": "percentage_points"},
        },
        "exit_advisory_effectiveness_v1": exit_advisory,
        "pretrade_entry_quality_v1": build_pretrade_entry_quality_assessment_v1(context),
        "truth_quality_score_v1": {
            "score": score,
            "grade": grade,
            "components": components,
            "missing_or_unavailable": missing,
            "explanation": "Passive learning-confidence annotation; strict-truth eligibility is unchanged.",
        },
    }
