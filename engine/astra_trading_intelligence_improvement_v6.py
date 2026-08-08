"""Read-only V6 pattern and realization intelligence for canonical strict truths."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from engine.astra_trading_intelligence_improvement_v2 import (
    METRIC_MINIMUM,
    SAFETY as V2_SAFETY,
    _field,
    _metrics,
    _number,
    _read,
    _return,
    _strict_truths,
    _text,
)
from engine.astra_trading_intelligence_improvement_v4 import build_trading_intelligence_improvement_suite_v4
from engine.astra_trading_intelligence_improvement_v5 import build_trading_intelligence_improvement_suite_v5


VERSION = "1.0.0"
MAX_MATCHES = 24
HUMAN_REVIEW_STRICT_MINIMUM = 20
SAFETY = {
    **V2_SAFETY,
    "execution_behavior_changed": False,
    "automatic_promotion_authority": False,
    "automatic_execution_adjustment": False,
    "provider_calls_added": 0,
    "broker_calls_used": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
}


def _context(row: Mapping[str, Any]) -> Mapping[str, Any]:
    value = row.get("pretrade_context_v1")
    return value if isinstance(value, Mapping) else {}


def _value(row: Mapping[str, Any], *keys: str) -> str:
    return _field(row, *keys, fallback="UNAVAILABLE")


def _query_value(query: Mapping[str, Any], key: str) -> str:
    value = query.get(key)
    return _text(value) if value not in (None, "", [], {}) else "UNAVAILABLE"


_SIMILARITY_FIELDS = {
    "symbol": ("symbol",),
    "asset_class": ("asset_class", "instrument_type"),
    "lane": ("lane_id", "lane"),
    "horizon": ("paper_entry_horizon_style", "intended_horizon", "horizon"),
    "regime": ("market_regime", "regime", "regime_context", "regime_fit"),
    "archetype": ("strategy_archetype", "archetype", "setup_type"),
    "catalyst": ("catalyst", "catalyst_state", "catalyst_type"),
    "momentum_state": ("momentum_state",),
    "volatility_context": ("volatility_context",),
}


def _similarity(rows: list[dict[str, Any]], shadow: Mapping[str, Any], query: Mapping[str, Any]) -> dict[str, Any]:
    requested = {key: _query_value(query, key) for key in _SIMILARITY_FIELDS}
    requested = {key: value for key, value in requested.items() if value != "UNAVAILABLE"}
    if not requested:
        return {
            "query_identity": {}, "status": "INSUFFICIENT_EVIDENCE", "similarity_quality": "UNAVAILABLE",
            "comparable_historical_outcomes": 0, "strict_truth_matches": [], "shadow_matches": [],
            "shadow_sample_size_separate": int(_number(shadow.get("completed_shadow_lifecycles")) or 0),
            "reason": "QUERY_CONTEXT_REQUIRED", "full_history_scan_count": 0,
        }
    matches = []
    for row in rows:
        compared = {key: _value(row, *keys) for key, keys in _SIMILARITY_FIELDS.items() if key in requested}
        matched = [key for key, value in compared.items() if value == requested[key] and value != "UNAVAILABLE"]
        known = [key for key, value in compared.items() if value != "UNAVAILABLE"]
        score = len(matched) / len(requested)
        if matched:
            matches.append({
                "lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"),
                "matched_dimensions": matched, "available_dimensions": known,
                "similarity_score": round(score, 4), "realized_return": _return(row),
                "evidence_tier": "BROKER_CONFIRMED_NATURAL_STRICT_TRUTH",
            })
    matches = sorted(matches, key=lambda item: (-item["similarity_score"], str(item.get("lifecycle_id") or "")))[:MAX_MATCHES]
    sample = len(matches)
    average_score = sum(item["similarity_score"] for item in matches) / sample if sample else 0.0
    if sample < METRIC_MINIMUM:
        status = "INSUFFICIENT_EVIDENCE"
    elif average_score >= 0.75 and len(requested) >= 3:
        status = "HIGH_SIMILARITY"
    elif average_score >= 0.5:
        status = "MODERATE_SIMILARITY"
    else:
        status = "LOW_SIMILARITY"
    return {
        "query_identity": requested, "status": status, "similarity_quality": status,
        "comparable_historical_outcomes": sample, "strict_truth_matches": matches,
        "shadow_matches": [], "shadow_match_status": "UNAVAILABLE_WITHOUT_CANDIDATE_LEVEL_SHADOW_INDEX",
        "shadow_sample_size_separate": int(_number(shadow.get("completed_shadow_lifecycles")) or 0),
        "historical_outcome_summary": _metrics([row for row in rows if any(item.get("lifecycle_id") == row.get("lifecycle_id") for item in matches)]) if sample >= METRIC_MINIMUM else {"metrics_status": "INSUFFICIENT_EVIDENCE"},
        "full_history_scan_count": 0,
    }


def _expected_upside(context: Mapping[str, Any]) -> float | None:
    value = context.get("expected_return_range")
    if isinstance(value, Mapping):
        return _number(value.get("high_pct") or value.get("high") or value.get("max_pct"))
    return _number(context.get("expected_return_high_pct") or context.get("expected_return_pct"))


def _prediction_error(row: Mapping[str, Any]) -> dict[str, Any]:
    context = _context(row)
    direction = _text(context.get("predicted_direction") or context.get("direction"))
    expected = _expected_upside(context)
    expected_downside = _number(context.get("expected_downside"))
    confidence = _number(context.get("confidence") or context.get("predicted_win_probability"))
    actual = _return(row)
    # Confidence alone is not an original trade prediction. Preserve legacy
    # rows as unavailable until a direction, magnitude, downside, or thesis
    # was actually captured before entry.
    if direction == "UNAVAILABLE" and expected is None and expected_downside is None and not context.get("thesis") and not context.get("entry_rationale"):
        return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": "UNAVAILABLE", "errors": [], "severity": "UNAVAILABLE"}
    errors: list[str] = []
    actual_direction = "UP" if actual is not None and actual > 0 else "DOWN" if actual is not None and actual < 0 else "UNAVAILABLE"
    normalized = {"BUY": "UP", "LONG": "UP", "BULLISH": "UP", "SELL": "DOWN", "SHORT": "DOWN", "BEARISH": "DOWN"}.get(direction, direction)
    if normalized in {"UP", "DOWN"} and actual_direction in {"UP", "DOWN"} and normalized != actual_direction:
        errors.append("DIRECTION_ERROR")
    if expected is not None and actual is not None and expected > 0 and actual < expected * 0.25:
        errors.append("MAGNITUDE_ERROR")
    if expected_downside is not None and actual is not None and actual < -abs(expected_downside):
        errors.append("RISK_UNDERESTIMATED")
    if confidence is not None and actual is not None:
        confidence = confidence * 100 if 0 < confidence <= 1 else confidence
        if confidence >= 80 and actual <= 0:
            errors.append("CONFIDENCE_OVERSTATED")
        elif confidence <= 40 and actual > 0:
            errors.append("CONFIDENCE_UNDERSTATED")
    if len(errors) > 1:
        errors.append("MULTI_FACTOR_ERROR")
    severity = "UNAVAILABLE" if not errors else "MAJOR" if "DIRECTION_ERROR" in errors or len(errors) >= 3 else "MODERATE" if len(errors) == 2 else "MINOR"
    return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": "OBSERVATIONAL", "errors": errors, "severity": severity}


def _risk_reward(row: Mapping[str, Any]) -> dict[str, Any]:
    context = _context(row)
    upside = _expected_upside(context)
    downside = _number(context.get("expected_downside"))
    mfe, mae, actual = _number(row.get("mfe")), _number(row.get("mae")), _return(row)
    if upside is None or downside is None or mfe is None or mae is None or actual is None:
        return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": "UNAVAILABLE"}
    expected_rr = upside / abs(downside) if downside else None
    actual_rr = actual / abs(mae) if mae else None
    if mae < -abs(downside):
        status = "DOWNSIDE_UNDERESTIMATED"
    elif mfe < upside * 0.5:
        status = "UPSIDE_OVERESTIMATED"
    elif mfe > upside * 1.5:
        status = "UPSIDE_UNDERESTIMATED"
    elif actual_rr is not None and actual_rr <= 0:
        status = "POOR_REALIZED_RISK_REWARD"
    else:
        status = "RISK_REWARD_ALIGNED"
    return {
        "lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": status,
        "expected_upside": upside, "expected_downside": downside, "expected_risk_reward": round(expected_rr, 4) if expected_rr is not None else None,
        "actual_mfe": mfe, "actual_mae": mae, "realized_return": actual,
        "realized_risk_reward": round(actual_rr, 4) if actual_rr is not None else None,
        "upside_capture_pct": round(actual * 100 / upside, 4) if upside else None,
        "downside_exceeded": mae < -abs(downside),
    }


def _expected_hold_seconds(context: Mapping[str, Any]) -> float | None:
    seconds = _number(context.get("expected_hold_seconds") or context.get("maximum_hold_seconds"))
    if seconds is not None:
        return seconds
    minutes = _number(context.get("expected_hold_minutes") or context.get("maximum_hold_minutes"))
    return minutes * 60 if minutes is not None else None


def _hold_duration(row: Mapping[str, Any]) -> dict[str, Any]:
    expected = _expected_hold_seconds(_context(row))
    actual = _number(row.get("hold_duration"))
    peak_time, giveback = _number(row.get("time_to_peak")), _number(row.get("profit_giveback"))
    if expected is None or actual is None:
        return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": "INSUFFICIENT_EVIDENCE"}
    if actual > expected * 1.5 and peak_time is not None and peak_time < expected and (giveback or 0) > 0:
        status = "HELD_TOO_LONG"
    elif actual > expected * 1.5 or actual < expected * 0.5:
        status = "HORIZON_MISMATCH_SUSPECTED"
    else:
        status = "HOLD_DURATION_ALIGNED"
    return {"lifecycle_id": row.get("lifecycle_id"), "symbol": row.get("symbol"), "status": status, "expected_hold_seconds": expected, "actual_hold_seconds": actual, "time_to_peak_seconds": peak_time, "profit_giveback": giveback, "automatic_exit_authority": False}


def _readiness(rows: list[dict[str, Any]], shadow: Mapping[str, Any], v4: Mapping[str, Any], v5: Mapping[str, Any]) -> dict[str, Any]:
    strict = len(rows)
    shadow_sample = int(_number(shadow.get("completed_shadow_lifecycles")) or 0)
    complete = sum(item.get("evidence_state") == "LEARNING_COMPLETE" for item in (v5.get("lifecycle_evidence_completeness") or {}).get("lifecycles", []))
    regimes = {_value(row, "market_regime", "regime", "regime_context") for row in rows} - {"UNAVAILABLE"}
    if strict < METRIC_MINIMUM:
        state = "NOT_READY"
    elif strict < 10 or complete < METRIC_MINIMUM:
        state = "COLLECT_MORE_EVIDENCE"
    elif strict < HUMAN_REVIEW_STRICT_MINIMUM or len(regimes) < 2:
        state = "OBSERVATIONAL_SIGNAL"
    else:
        state = "REPEATABLE_SIGNAL"
    return {
        "status": state, "strict_truth_sample_size": strict, "shadow_sample_size_separate": shadow_sample,
        "learning_complete_truths": complete, "regime_diversity": len(regimes),
        "v4_drift_status": ((v4.get("learning_consistency_and_drift") or {}).get("status") or "INSUFFICIENT_EVIDENCE"),
        "human_review_eligible": False, "automatic_promotion_disabled": True,
        "blockers": ["STRICT_TRUTH_SAMPLE_BELOW_5"] if strict < METRIC_MINIMUM else ["BROKER_BACKED_REPEATABILITY_REQUIRED"],
        "shadow_can_strengthen_but_not_replace_strict_truth": True,
    }


def build_trading_intelligence_improvement_suite_v6(state_dir: str = "state", query: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build bounded V6 observations without changing lifecycle or policy state."""
    state = Path(state_dir)
    rows = _strict_truths(_read(state / "broker_truth_records_v1.json"))
    shadow = _read(state / "dashboard_cache" / "realistic_shadow_evidence_learning_lab_v1.json")
    v5 = build_trading_intelligence_improvement_suite_v5(state_dir, query)
    v4 = build_trading_intelligence_improvement_suite_v4(state_dir, query)
    errors = [_prediction_error(row) for row in rows]
    return {
        "suite": "ASTRA Trading Intelligence Improvement Suite V6", "version": VERSION,
        "status": "OBSERVATIONAL_READY" if rows else "INSUFFICIENT_EVIDENCE",
        "strict_truth_sample_size": len(rows), "shadow_sample_size_separate": int(_number(shadow.get("completed_shadow_lifecycles")) or 0),
        "trade_pattern_similarity": _similarity(rows, shadow, query or {}),
        "prediction_error_decomposition": {"status": "OBSERVATIONAL" if any(item["status"] == "OBSERVATIONAL" for item in errors) else "UNAVAILABLE", "errors": errors[:MAX_MATCHES], "error_counts": dict(Counter(error for item in errors for error in item.get("errors", []))), "post_hoc_reconstruction_used": False},
        "risk_reward_realization": {"observations": [_risk_reward(row) for row in rows][:MAX_MATCHES], "status": "INSUFFICIENT_EVIDENCE" if len(rows) < METRIC_MINIMUM else "OBSERVATIONAL", "risk_envelope_changed": False},
        "hold_duration_optimization": {"observations": [_hold_duration(row) for row in rows][:MAX_MATCHES], "status": "INSUFFICIENT_EVIDENCE" if len(rows) < METRIC_MINIMUM else "OBSERVATIONAL", "horizon_owner": "EXISTING_V3_HORIZON_OWNERSHIP", "automatic_exit_authority": False},
        "learning_promotion_readiness": _readiness(rows, shadow, v4, v5),
        "v1_v5_continuity": {"v4_status": v4.get("status"), "v5_status": v5.get("status"), "frozen_lifecycle_modified": False, "full_history_scan_count": 0},
        "warnings": ["STRICT_TRUTH_SAMPLE_INSUFFICIENT", "ORIGINAL_PREDICTION_CONTEXT_MISSING", "EXCURSION_EVIDENCE_ACCUMULATING"],
        **SAFETY,
    }
