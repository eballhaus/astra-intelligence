from __future__ import annotations

import json
import math
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from statistics import mean, median
from typing import Any

from engine.learning_return_integrity_v1 import official_broker_confirmed_rows

VERSION = "1.0.0"
TRADE_EFFECTIVENESS_V2_SCHEMA = "astra_profit_capture_trade_effectiveness_v2"
MAX_EFFECTIVENESS_TRUTHS = 80
MAX_TAIL_BYTES = 1_800_000
MAX_ROWS = 1500
MIN_STABLE_RETURN_NORMALIZATION_SECONDS = 60.0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return float(default)
        out = float(value)
        return out if math.isfinite(out) else float(default)
    except Exception:
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(_to_float(value, default))
    except Exception:
        return int(default)


def _text(value: Any, default: str = "") -> str:
    text = str(value if value is not None else default).strip()
    return text or str(default)


def _round(value: Any, digits: int = 4) -> float:
    return round(_to_float(value), digits)


def _clamp(value: Any, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, _to_float(value, low)))


def _tail_jsonl(path: str, max_rows: int = MAX_ROWS, max_bytes: int = MAX_TAIL_BYTES) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as handle:
            handle.seek(max(0, size - max_bytes))
            text = handle.read().decode("utf-8", "ignore")
    except Exception:
        return []
    lines = text.splitlines()
    if size > max_bytes and lines:
        lines = lines[1:]
    rows: list[dict[str, Any]] = []
    for line in lines[-max_rows:]:
        try:
            parsed = json.loads(line)
            if isinstance(parsed, dict):
                rows.append(parsed)
        except Exception:
            continue
    return rows


def load_bounded_broker_truth_records_v1(
    state_dir: str,
    *,
    limit: int = MAX_EFFECTIVENESS_TRUTHS,
) -> list[dict[str, Any]]:
    """Read the existing compact canonical registry when runtime has no rows."""
    try:
        with open(os.path.join(str(state_dir), "broker_truth_records_v1.json"), "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return []
    rows = payload.get("records") if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        return []
    return [dict(row) for row in rows[-max(1, int(limit)):] if isinstance(row, dict)]


def _capture_label(capture_ratio: float, peak: float, closed: bool) -> str:
    if not closed:
        return "still_open_learning"
    if peak <= 0.05:
        return "no_profit_available"
    if capture_ratio >= 0.80:
        return "excellent_capture"
    if capture_ratio >= 0.60:
        return "good_capture"
    if capture_ratio >= 0.40:
        return "acceptable_capture"
    if capture_ratio >= 0.20:
        return "weak_capture"
    return "severe_giveback"


def _giveback_label(giveback: float, peak: float) -> str:
    if peak <= 0.05:
        return "no_profit_available"
    ratio = giveback / peak if peak > 0 else 0.0
    if ratio < 0.20 and giveback < 0.35:
        return "no_action_needed"
    if ratio < 0.40:
        return "monitor_profit_giveback"
    if ratio < 0.65:
        return "profit_capture_watch"
    return "high_giveback_watch"


def _giveback_pattern(row: dict[str, Any], peak: float, giveback: float, capture_ratio: float, time_to_peak: float) -> str:
    follow_label = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")).lower()
    sector = _text(row.get("sector"), "unknown").lower()
    regime = _text(row.get("market_regime"), "unknown").lower()
    mae = _to_float(row.get("max_adverse_excursion_pct"))
    hold_minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
    if giveback <= 0.25 or peak <= 0.25:
        return "minimal_giveback"
    if time_to_peak > 0 and time_to_peak <= 30 and giveback >= 0.75:
        return "fast_spike"
    if "failed" in follow_label or "stalled" in follow_label:
        return "failed_continuation"
    if mae <= -1.5 and giveback >= 0.75:
        return "volatility_reversal"
    if capture_ratio < 0.25 and peak >= 1.5:
        return "high_volatility_exhaustion"
    if "risk_off" in regime or "bear" in regime:
        return "market_regime_shift"
    if sector not in {"", "unknown"} and giveback >= 1.0:
        return "sector_fade"
    if hold_minutes >= 300 and giveback >= 0.75:
        return "slow_grind"
    return "profit_decay"


def _context_key(row: dict[str, Any]) -> str:
    return (
        f"{_text(row.get('sector'), 'unknown')}:"
        f"{_text(row.get('cap_tier'), 'unknown')}:"
        f"{_text(row.get('horizon_style'), 'unknown')}"
    )


def _optional_number(value: Any) -> float | None:
    if value is None or value == "" or isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _first_number(row: dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = _optional_number(row.get(key))
        if value is not None:
            return value
    return None


def _nested_learning(row: dict[str, Any]) -> dict[str, Any]:
    learning = row.get("observational_learning_v1")
    if not isinstance(learning, dict):
        return {}
    hold = learning.get("hold_quality_exit_timing_v1")
    return dict(hold) if isinstance(hold, dict) else {}


def _strict_completed_truth(row: dict[str, Any]) -> bool:
    quality = _text(row.get("truth_quality")).upper()
    state = _text(row.get("truth_state")).upper()
    strict = quality == "BROKER_CONFIRMED_COMPLETE" or state in {"STRICT_TRUTH", "BROKER_TRUTH_CONFIRMED"} or bool(row.get("strict_broker_truth"))
    return bool(strict and _text(row.get("entry_fill_id")) and _text(row.get("exit_fill_id")))


def _canonical_lane(row: dict[str, Any]) -> str:
    return _text(row.get("lane_id") or row.get("lane") or row.get("allocation_lane"), "UNAVAILABLE").upper()


def _canonical_horizon(row: dict[str, Any]) -> str:
    context = row.get("pretrade_context_v1")
    context = dict(context) if isinstance(context, dict) else {}
    return _text(
        row.get("intended_horizon") or row.get("horizon") or row.get("horizon_style")
        or context.get("intended_horizon") or context.get("horizon") or context.get("paper_entry_horizon_style"),
        "UNAVAILABLE",
    )


def _parse_timestamp(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _exact_hold_seconds(row: dict[str, Any]) -> tuple[float | None, str | None, str | None]:
    entry_timestamp = _text(row.get("entry_timestamp") or row.get("entry_time") or row.get("entry_filled_at")) or None
    exit_timestamp = _text(row.get("exit_timestamp") or row.get("exit_time") or row.get("exit_filled_at") or row.get("filled_at")) or None
    entry_dt = _parse_timestamp(entry_timestamp)
    exit_dt = _parse_timestamp(exit_timestamp)
    if entry_dt is None or exit_dt is None:
        return None, entry_timestamp, exit_timestamp
    elapsed = (exit_dt - entry_dt).total_seconds()
    return (elapsed if elapsed > 0 else None), entry_timestamp, exit_timestamp


def _dimension_state(value: Any) -> str:
    raw = _text(value).upper()
    if raw in {"SUPPORTED_POSITIVE", "POSITIVE", "PASS", "ALIGNED", "EFFECTIVE", "GOOD"}:
        return "SUPPORTED_POSITIVE"
    if raw in {"SUPPORTED_NEGATIVE", "NEGATIVE", "FAIL", "MISALIGNED", "POOR", "FAILED", "DETERIORATED"}:
        return "SUPPORTED_NEGATIVE"
    if raw in {"NEUTRAL", "MIXED"}:
        return "NEUTRAL"
    if raw in {"CONTRADICTORY", "CONFLICT"}:
        return "CONTRADICTORY"
    return "UNAVAILABLE"


def _dimension(row: dict[str, Any], notes: dict[str, Any], name: str, *keys: str) -> dict[str, Any]:
    for key in keys:
        value = row.get(key) if key in row else notes.get(key)
        if value not in (None, "", "UNAVAILABLE", "unknown"):
            return {
                "dimension": name,
                "state": _dimension_state(value),
                "value": value,
                "source": "broker_truth_records_v1" if key in row else "canonical_lifecycle_excursion_v2",
                "evidence_timestamp": row.get("exit_timestamp") or row.get("exit_time"),
                "evidence_ids": [value for value in (row.get("truth_id") or row.get("stable_key"), row.get("lifecycle_id")) if value],
            }
    return {
        "dimension": name,
        "state": "UNAVAILABLE",
        "value": None,
        "source": None,
        "evidence_timestamp": None,
        "evidence_ids": [],
    }


def _first_driver(dimensions: list[dict[str, Any]], state: str) -> str | None:
    return next((row["dimension"] for row in dimensions if row.get("state") == state), None)


def _loss_anatomy(
    *,
    row: dict[str, Any],
    realized: float | None,
    peak: float | None,
    capture_label: str,
    exit_effectiveness: str,
    hold_seconds: float | None,
    expected_hold_seconds: float | None,
    dimensions: list[dict[str, Any]],
    exit_timestamp: str | None,
) -> dict[str, Any]:
    if realized is None:
        return {"loss_classification": "INSUFFICIENT_EVIDENCE", "preventability": "NOT_PROVEN", "primary_cause": "missing_realized_return"}
    if realized >= 0:
        return {"loss_classification": "NOT_A_LOSS", "preventability": "NOT_PROVEN", "primary_cause": None}
    exit_reason = _text(row.get("exit_reason")).upper()
    exit_trigger = _parse_timestamp(row.get("exit_trigger_timestamp") or row.get("deterioration_observed_at"))
    exit_time = _parse_timestamp(exit_timestamp)
    if exit_trigger and exit_time and exit_time > exit_trigger:
        return {"loss_classification": "PREVENTABLE_EXIT_DELAY", "preventability": "PREVENTABLE", "primary_cause": "proven_exit_trigger_before_exit"}
    deterioration = _parse_timestamp(row.get("momentum_deterioration_observed_at") or row.get("profit_protection_triggered_at"))
    if peak is not None and peak > 0 and capture_label == "SEVERE_GIVEBACK" and deterioration and exit_time and exit_time > deterioration:
        return {"loss_classification": "PREVENTABLE_PROFIT_GIVEBACK", "preventability": "PREVENTABLE", "primary_cause": "proven_deterioration_before_severe_giveback"}
    if expected_hold_seconds and hold_seconds and hold_seconds > expected_hold_seconds:
        return {"loss_classification": "PREVENTABLE_OVERHOLD", "preventability": "PARTLY_PREVENTABLE", "primary_cause": "proven_expected_horizon_exceeded"}
    if _text(row.get("execution_error_state")).upper() == "EXECUTION_ERROR":
        return {"loss_classification": "EXECUTION_ERROR", "preventability": "NOT_PROVEN", "primary_cause": "broker_execution_error_evidence"}
    if _first_driver(dimensions, "SUPPORTED_NEGATIVE") == "regime_context":
        return {"loss_classification": "REGIME_MISMATCH", "preventability": "PARTLY_PREVENTABLE", "primary_cause": "supported_regime_mismatch"}
    if _first_driver(dimensions, "SUPPORTED_NEGATIVE") in {"selection_quality", "entry_timing"}:
        return {"loss_classification": "PREVENTABLE_ENTRY_ERROR", "preventability": "PARTLY_PREVENTABLE", "primary_cause": "supported_pretrade_entry_quality_failure"}
    if any(token in exit_reason for token in ("STOP", "THESIS", "RISK", "LOSS", "INVALIDATION")):
        classification = "THESIS_FAILED_ACCEPTABLE" if "THESIS" in exit_reason or "INVALIDATION" in exit_reason else "CONTROLLED_EXPECTED_LOSS"
        return {"loss_classification": classification, "preventability": "CONTROLLED", "primary_cause": "authorized_loss_containment_exit"}
    return {"loss_classification": "INSUFFICIENT_EVIDENCE", "preventability": "NOT_PROVEN", "primary_cause": None}


def _mean_optional(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(mean(clean), 6) if clean else None


def _median_optional(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(float(median(clean)), 6) if clean else None


def _peak_evidence_state(row: dict[str, Any]) -> str:
    for key in ("peak_evidence_freshness", "mfe_evidence_freshness", "excursion_evidence_freshness", "peak_evidence_state"):
        state = _text(row.get(key)).upper()
        if state in {"STALE", "RECONSTRUCTED", "DIAGNOSTIC", "HISTORICAL_RECONSTRUCTED"}:
            return "STALE_OR_RECONSTRUCTED_EVIDENCE"
    return "CANONICAL_EXCURSION_EVIDENCE"


def _exit_effectiveness(*, realized: float | None, peak: float | None, capture: float | None, exit_reason: str, hold_seconds: float | None, expected_hold_seconds: float | None) -> str:
    if realized is None or peak is None:
        return "INSUFFICIENT_EVIDENCE"
    if peak <= 0:
        if realized < 0 and any(token in exit_reason.upper() for token in ("STOP", "THESIS", "RISK", "LOSS", "INVALIDATION")):
            return "LOSS_ACCEPTANCE_EFFECTIVE"
        if realized < 0 and expected_hold_seconds and hold_seconds and hold_seconds > expected_hold_seconds:
            return "LOSS_HELD_TOO_LONG"
        return "INSUFFICIENT_EVIDENCE"
    if capture is None:
        return "INSUFFICIENT_EVIDENCE"
    if capture >= 0.80:
        return "EFFECTIVE"
    if capture <= 0.20:
        return "SEVERE_PROFIT_GIVEBACK"
    if capture < 0.40:
        return "LATE"
    return "EFFECTIVE"


def _management_attribution(*, realized: float | None, peak: float | None, capture: float | None, exit_effectiveness: str, horizon_assessment: str) -> str:
    if realized is None or peak is None:
        return "DATA_OR_TRUTH_INCOMPLETE"
    if "EXCEEDED" in horizon_assessment.upper() or "MISMATCH" in horizon_assessment.upper():
        return "HORIZON_MISMATCH"
    if realized > 0 and capture is not None and capture >= 0.80:
        return "GOOD_ENTRY_GOOD_MANAGEMENT_GOOD_EXIT"
    if peak > 0 and exit_effectiveness in {"LATE", "SEVERE_PROFIT_GIVEBACK"}:
        return "GOOD_ENTRY_LATE_EXIT"
    if peak > 0 and realized > 0:
        return "GOOD_ENTRY_POOR_MANAGEMENT"
    if exit_effectiveness == "LOSS_ACCEPTANCE_EFFECTIVE":
        return "POOR_ENTRY_EFFECTIVE_LOSS_CONTROL"
    if realized <= 0:
        return "POOR_ENTRY_POOR_EXIT"
    return "INSUFFICIENT_EVIDENCE"


def _effectiveness_row(row: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Derive only from an already-confirmed broker truth and its attached facts."""
    notes = _nested_learning(row)
    lifecycle_id = _text(row.get("lifecycle_id"))
    peak_state = _peak_evidence_state(row)
    peak = None if peak_state != "CANONICAL_EXCURSION_EVIDENCE" else _first_number(
        row, "max_favorable_excursion_pct", "maximum_favorable_excursion_pct", "mfe", "peak_return_percent", "peak_unrealized_profit_pct",
    )
    if peak is None and peak_state == "CANONICAL_EXCURSION_EVIDENCE":
        peak = _first_number(notes, "maximum_favorable_excursion_pct", "mfe_pct")
    realized = _first_number(row, "realized_return", "realized_return_pct", "actual_return_pct", "pnl_pct", "exit_gain_pct")
    if realized is None:
        realized = _first_number(notes, "actual_return_pct")
    reported_hold_seconds = _first_number(row, "hold_duration_seconds", "hold_time_seconds", "actual_hold_seconds")
    if reported_hold_seconds is None:
        reported_hold_seconds = _first_number(notes, "hold_duration_seconds")
    exact_hold_seconds, entry_timestamp, exact_exit_timestamp = _exact_hold_seconds(row)
    hold_seconds = exact_hold_seconds if exact_hold_seconds is not None else reported_hold_seconds
    context = row.get("pretrade_context_v1")
    context = dict(context) if isinstance(context, dict) else {}
    expected_hold_seconds = _first_number(row, "maximum_hold_seconds", "expected_hold_seconds")
    if expected_hold_seconds is None:
        expected_hold_seconds = _first_number(context, "maximum_hold_seconds", "expected_hold_seconds")
    if expected_hold_seconds is None:
        minutes = _first_number(row, "expected_hold_minutes", "maximum_hold_minutes")
        if minutes is None:
            minutes = _first_number(context, "expected_hold_minutes", "maximum_hold_minutes")
        expected_hold_seconds = minutes * 60.0 if minutes is not None else None
    if expected_hold_seconds is None:
        days = _first_number(row, "expected_hold_days")
        if days is None:
            days = _first_number(context, "expected_hold_days")
        expected_hold_seconds = days * 86400.0 if days is not None else None
    peak_timestamp = _text(row.get("peak_timestamp") or row.get("peak_observed_at") or row.get("mfe_timestamp") or row.get("time_of_peak")) or None
    exit_timestamp = exact_exit_timestamp or _text(row.get("exit_time") or row.get("exit_timestamp") or row.get("filled_at")) or None
    time_after_peak = None
    if peak_timestamp and exit_timestamp:
        try:
            peak_dt = datetime.fromisoformat(peak_timestamp.replace("Z", "+00:00"))
            exit_dt = datetime.fromisoformat(exit_timestamp.replace("Z", "+00:00"))
            time_after_peak = max(0.0, (exit_dt - peak_dt).total_seconds())
        except ValueError:
            time_after_peak = None
    if time_after_peak is None and hold_seconds is not None:
        time_to_peak = _first_number(row, "time_to_peak_seconds", "time_to_peak")
        if time_to_peak is not None:
            time_after_peak = max(0.0, hold_seconds - time_to_peak)

    never_profitable = peak is not None and peak <= 0
    capture = None
    giveback = None
    giveback_pct = None
    if peak is not None and peak > 0 and realized is not None:
        capture = max(0.0, min(1.0, max(0.0, realized) / peak))
        giveback = max(0.0, peak - realized)
        giveback_pct = (giveback / peak) * 100.0
    if never_profitable:
        capture_label = "NEVER_PROFITABLE"
    elif capture is None:
        capture_label = "INSUFFICIENT_EVIDENCE"
    elif capture >= 0.80:
        capture_label = "EXCELLENT_CAPTURE"
    elif capture >= 0.60:
        capture_label = "GOOD_CAPTURE"
    elif capture >= 0.40:
        capture_label = "MODERATE_GIVEBACK"
    elif capture >= 0.20:
        capture_label = "HIGH_GIVEBACK"
    else:
        capture_label = "SEVERE_GIVEBACK"
    exit_reason = _text(row.get("exit_reason") or notes.get("exit_reason"), "UNAVAILABLE")
    horizon_assessment = _text(notes.get("hold_horizon_assessment"), "UNAVAILABLE")
    exit_effectiveness = _exit_effectiveness(
        realized=realized, peak=peak, capture=capture, exit_reason=exit_reason,
        hold_seconds=hold_seconds, expected_hold_seconds=expected_hold_seconds,
    )
    signals = {
        key: value for key, value in {
            "momentum_deterioration": row.get("momentum_deterioration_score") or notes.get("momentum_state_at_exit"),
            "thesis_deterioration": notes.get("thesis_state_at_exit"),
            "return_per_day_decay": row.get("return_per_day_decay") or notes.get("return_per_day"),
            "opportunity_cost": notes.get("opportunity_cost_state") or row.get("opportunity_cost_state"),
            "horizon_pressure": horizon_assessment if horizon_assessment != "UNAVAILABLE" else None,
        }.items() if value not in (None, "", "UNAVAILABLE", "unknown")
    }
    opportunity = _text(signals.get("opportunity_cost"), "UNAVAILABLE").upper()
    opportunity_state = (
        "HIGH_OPPORTUNITY_COST" if "HIGH" in opportunity else
        "REPLACEMENT_OPPORTUNITY_PRESENT" if any(token in opportunity for token in ("REPLACE", "OPPORTUNITY")) else
        "NO_MEANINGFUL_REPLACEMENT" if opportunity in {"NONE", "NO_MEANINGFUL_REPLACEMENT"} else
        "INSUFFICIENT_EVIDENCE"
    )
    dimensions = [
        _dimension(row, notes, "selection_quality", "selection_quality_state", "ranking_attribution_state"),
        _dimension(row, notes, "entry_timing", "entry_timing_state", "entry_quality_state"),
        _dimension(row, notes, "confidence_forecast_alignment", "confidence_forecast_alignment_state", "forecast_alignment_state"),
        _dimension(row, notes, "regime_context", "regime_attribution_state", "regime_fit_state"),
        _dimension(row, notes, "catalyst_context", "catalyst_attribution_state", "catalyst_fit_state"),
        _dimension(row, notes, "sector_context", "sector_attribution_state", "sector_fit_state"),
        _dimension(row, notes, "momentum_follow_through", "momentum_attribution_state", "follow_through_state"),
        _dimension(row, notes, "risk_downside", "risk_attribution_state", "risk_envelope_state"),
        _dimension(row, notes, "execution_quality", "execution_error_state", "slippage_attribution_state"),
    ]
    exit_state = "SUPPORTED_NEGATIVE" if exit_effectiveness in {"LATE", "SEVERE_PROFIT_GIVEBACK", "LOSS_HELD_TOO_LONG"} else "SUPPORTED_POSITIVE" if exit_effectiveness in {"EFFECTIVE", "LOSS_ACCEPTANCE_EFFECTIVE"} else "UNAVAILABLE"
    dimensions.append({"dimension": "exit_timing_quality", "state": exit_state, "value": exit_effectiveness, "source": "adaptive_profit_capture_intelligence_v1.exit_effectiveness", "evidence_timestamp": exit_timestamp, "evidence_ids": [value for value in (row.get("truth_id") or row.get("stable_key"), lifecycle_id) if value]})
    giveback_state = "SUPPORTED_NEGATIVE" if capture_label in {"HIGH_GIVEBACK", "SEVERE_GIVEBACK"} else "SUPPORTED_POSITIVE" if capture_label in {"EXCELLENT_CAPTURE", "GOOD_CAPTURE"} else "NEUTRAL" if capture_label == "MODERATE_GIVEBACK" else "UNAVAILABLE"
    dimensions.append({"dimension": "peak_giveback", "state": giveback_state, "value": capture_label, "source": "canonical lifecycle excursion evidence", "evidence_timestamp": peak_timestamp or exit_timestamp, "evidence_ids": [value for value in (row.get("truth_id") or row.get("stable_key"), lifecycle_id) if value]})
    opportunity_dimension_state = "SUPPORTED_NEGATIVE" if opportunity_state in {"HIGH_OPPORTUNITY_COST", "REPLACEMENT_OPPORTUNITY_PRESENT"} else "NEUTRAL" if opportunity_state == "NO_MEANINGFUL_REPLACEMENT" else "UNAVAILABLE"
    dimensions.append({"dimension": "opportunity_cost", "state": opportunity_dimension_state, "value": opportunity_state, "source": "canonical lifecycle excursion evidence" if opportunity_state != "INSUFFICIENT_EVIDENCE" else None, "evidence_timestamp": exit_timestamp, "evidence_ids": [lifecycle_id] if lifecycle_id else []})
    loss_anatomy = _loss_anatomy(
        row=row, realized=realized, peak=peak, capture_label=capture_label,
        exit_effectiveness=exit_effectiveness, hold_seconds=hold_seconds,
        expected_hold_seconds=expected_hold_seconds, dimensions=dimensions,
        exit_timestamp=exit_timestamp,
    )
    supporting = [item for item in dimensions if item.get("state") in {"SUPPORTED_POSITIVE", "SUPPORTED_NEGATIVE"}]
    attribution_status = "CONTRADICTORY" if any(item.get("state") == "CONTRADICTORY" for item in dimensions) else "SUPPORTED" if supporting else "INSUFFICIENT_EVIDENCE"
    primary_success_driver = _first_driver(dimensions, "SUPPORTED_POSITIVE") if realized is not None and realized > 0 else None
    primary_failure_driver = loss_anatomy.get("primary_cause") if realized is not None and realized < 0 else None
    stable_normalization = bool(exact_hold_seconds and exact_hold_seconds >= MIN_STABLE_RETURN_NORMALIZATION_SECONDS)
    realized_return_per_hour = round(realized / (exact_hold_seconds / 3600.0), 6) if realized is not None and stable_normalization else None
    realized_return_per_day = round(realized / (exact_hold_seconds / 86400.0), 6) if realized is not None and stable_normalization else None
    peak_return_per_day = round(peak / (exact_hold_seconds / 86400.0), 6) if peak is not None and stable_normalization else None
    committed_capital = _first_number(row, "committed_capital", "capital_committed", "position_capital")
    realized_pnl = _first_number(row, "realized_pnl", "realized_profit")
    capital_time_efficiency = (
        round(realized_pnl / (committed_capital * (exact_hold_seconds / 3600.0)), 8)
        if realized_pnl is not None and committed_capital and committed_capital > 0 and stable_normalization else None
    )
    integrity_fact = None
    mfe_marked_available = bool(row.get("mfe_evidence_available"))
    if peak is None:
        integrity_fact = {
            "kind": (
                "EFFECTIVENESS_PEAK_EVIDENCE_LOSS" if mfe_marked_available and peak_state == "CANONICAL_EXCURSION_EVIDENCE"
                else "HISTORICAL" if peak_state != "CANONICAL_EXCURSION_EVIDENCE"
                else "PRODUCER_MISSING"
            ),
            "current": peak_state == "CANONICAL_EXCURSION_EVIDENCE",
            "lifecycle_id": lifecycle_id,
            "symbol": row.get("symbol"),
            "lane": _canonical_lane(row),
            "producer": "canonical lifecycle excursion evidence",
            "consumer": "adaptive_profit_capture_intelligence_v1.trade_effectiveness_v2",
            "field": "maximum_favorable_excursion_pct",
            "producer_value_available": mfe_marked_available,
            "consumer_value": None,
            "producer_value": "AVAILABLE" if mfe_marked_available else None,
            "evidence_timestamp": exit_timestamp,
            "first_bad_handoff": "canonical lifecycle excursion evidence -> profit-capture effectiveness analysis",
        }
    return {
        "lifecycle_id": lifecycle_id,
        "truth_id": _text(row.get("truth_id") or row.get("stable_key")) or None,
        "position_id": _text(row.get("position_id")) or None,
        "symbol": _text(row.get("symbol")).upper(),
        "lane": _canonical_lane(row),
        "horizon": _canonical_horizon(row),
        "broker_truth_tier": "BROKER_STRICT_TRUTH",
        "partial_exit_handling": "FINAL_BROKER_CONFIRMED_REALIZED_RETURN" if bool(row.get("partial_exit_count") or row.get("partial_exit")) else "SINGLE_FINAL_EXIT",
        "peak_unrealized_return_pct": round(peak, 6) if peak is not None else None,
        "realized_return_pct": round(realized, 6) if realized is not None else None,
        "profit_capture_pct": round(capture * 100.0, 6) if capture is not None else None,
        "profit_giveback_pct": round(giveback, 6) if giveback is not None else None,
        "profit_giveback_from_peak_pct": round(giveback_pct, 6) if giveback_pct is not None else None,
        "profit_capture_classification": capture_label,
        "exit_effectiveness": exit_effectiveness,
        "entry_management_exit_attribution": _management_attribution(
            realized=realized, peak=peak, capture=capture, exit_effectiveness=exit_effectiveness, horizon_assessment=horizon_assessment,
        ),
        "decision_attribution": {
            "dimensions": dimensions,
            "primary_success_driver": primary_success_driver,
            "primary_failure_driver": primary_failure_driver,
            "secondary_drivers": [item["dimension"] for item in supporting if item["dimension"] not in {primary_success_driver, primary_failure_driver}][:6],
            "attribution_status": attribution_status,
            "attribution_confidence": "SUPPORTED_CANONICAL_EVIDENCE" if supporting else "INSUFFICIENT_EVIDENCE",
        },
        "loss_anatomy": {
            **loss_anatomy,
            "supporting_lifecycle_id": lifecycle_id or None,
            "supporting_truth_id": _text(row.get("truth_id") or row.get("stable_key")) or None,
            "expected_loss_pct": _first_number(row, "expected_downside_pct", "expected_loss_pct"),
            "actual_loss_pct": realized if realized is not None and realized < 0 else None,
        },
        "entry_timestamp": entry_timestamp,
        "hold_duration_seconds": round(exact_hold_seconds, 6) if exact_hold_seconds is not None else None,
        "reported_hold_duration_seconds": round(reported_hold_seconds, 6) if reported_hold_seconds is not None else None,
        "hold_minutes": round(exact_hold_seconds / 60.0, 6) if exact_hold_seconds is not None else None,
        "hold_hours": round(exact_hold_seconds / 3600.0, 6) if exact_hold_seconds is not None else None,
        "expected_hold_seconds": round(expected_hold_seconds, 6) if expected_hold_seconds is not None else None,
        "expected_vs_actual_hold_ratio": round(exact_hold_seconds / expected_hold_seconds, 6) if exact_hold_seconds is not None and expected_hold_seconds and expected_hold_seconds > 0 else None,
        "time_normalization_state": "STABLE" if stable_normalization else "NORMALIZATION_UNSTABLE",
        "realized_return_per_hour": realized_return_per_hour,
        "realized_return_per_day": realized_return_per_day,
        "peak_return_per_day": peak_return_per_day,
        "capital_time_efficiency": capital_time_efficiency,
        "peak_timestamp": peak_timestamp,
        "exit_timestamp": exit_timestamp,
        "time_after_peak_seconds": round(time_after_peak, 6) if time_after_peak is not None else None,
        "existing_exit_quality_score": _first_number(row, "exit_quality_score") or _first_number(notes, "exit_quality_score"),
        "momentum_profit_protection_evidence": signals or "UNAVAILABLE",
        "opportunity_cost_classification": opportunity_state,
        "evidence_quality": "BROKER_TRUTH_WITH_CANONICAL_EXCURSION" if peak is not None else peak_state,
        "provenance": {"truth_record": "broker_truth_records_v1", "excursion": "canonical lifecycle evidence", "shadow_promoted": False},
    }, integrity_fact


def build_profit_capture_trade_effectiveness_v2(
    broker_truth_records: list[dict[str, Any]] | None,
    *,
    shadow_exit_performance: dict[str, Any] | None = None,
    shadow_exit_outputs: dict[str, Any] | None = None,
    limit: int = MAX_EFFECTIVENESS_TRUTHS,
) -> dict[str, Any]:
    """Bounded, read-only effectiveness summary for completed strict broker truths.

    Shadow aggregates are reported separately and never contribute to official
    broker-truth metrics or promotion authority.
    """
    official_rows: list[dict[str, Any]] = []
    integrity_facts: list[dict[str, Any]] = []
    bounded_truths = [dict(raw) for raw in list(broker_truth_records or [])[-max(1, int(limit)):] if isinstance(raw, dict)]
    return_integrity_truths = official_broker_confirmed_rows(bounded_truths, max_rows=limit)
    excluded = len(bounded_truths) - len(return_integrity_truths)
    for raw in return_integrity_truths:
        if not _strict_completed_truth(raw) or _text(raw.get("legacy_status")).upper() == "LEGACY":
            excluded += 1
            continue
        derived, fact = _effectiveness_row(dict(raw))
        official_rows.append(derived)
        if fact is not None:
            integrity_facts.append(fact)
    captures = [row.get("profit_capture_pct") for row in official_rows]
    givebacks = [row.get("profit_giveback_from_peak_pct") for row in official_rows]
    realized_per_day = [row.get("realized_return_per_day") for row in official_rows]
    realized_per_hour = [row.get("realized_return_per_hour") for row in official_rows]
    after_peak = [row.get("time_after_peak_seconds") for row in official_rows]
    counts = Counter(_text(row.get("exit_effectiveness"), "INSUFFICIENT_EVIDENCE") for row in official_rows)
    loss_counts = Counter(_text((row.get("loss_anatomy") or {}).get("loss_classification"), "INSUFFICIENT_EVIDENCE") for row in official_rows)
    preventability_counts = Counter(_text((row.get("loss_anatomy") or {}).get("preventability"), "NOT_PROVEN") for row in official_rows)
    success_drivers = Counter(_text((row.get("decision_attribution") or {}).get("primary_success_driver"), "UNAVAILABLE") for row in official_rows)
    failure_drivers = Counter(_text((row.get("decision_attribution") or {}).get("primary_failure_driver"), "UNAVAILABLE") for row in official_rows)
    lanes: dict[str, dict[str, Any]] = {}
    for lane in ("SCALP", "DAY", "SWING", "CRYPTO"):
        rows = [row for row in official_rows if row.get("lane") == lane]
        lanes[lane] = {
            "completed_broker_truth_sample_size": len(rows),
            "average_profit_capture_pct": _mean_optional([row.get("profit_capture_pct") for row in rows]),
            "average_profit_giveback_from_peak_pct": _mean_optional([row.get("profit_giveback_from_peak_pct") for row in rows]),
            "average_hold_duration_seconds": _mean_optional([row.get("hold_duration_seconds") for row in rows]),
            "average_time_after_peak_seconds": _mean_optional([row.get("time_after_peak_seconds") for row in rows]),
            "average_realized_return_per_day": _mean_optional([row.get("realized_return_per_day") for row in rows]),
            "average_realized_return_per_hour": _mean_optional([row.get("realized_return_per_hour") for row in rows]),
            "effective_exit_count": sum(row.get("exit_effectiveness") == "EFFECTIVE" for row in rows),
            "late_exit_count": sum(row.get("exit_effectiveness") in {"LATE", "SEVERE_PROFIT_GIVEBACK"} for row in rows),
            "controlled_loss_effective_count": sum(row.get("exit_effectiveness") == "LOSS_ACCEPTANCE_EFFECTIVE" for row in rows),
        }
    horizons: dict[str, dict[str, Any]] = {}
    for horizon in sorted({_text(row.get("horizon"), "UNAVAILABLE") for row in official_rows}):
        rows = [row for row in official_rows if row.get("horizon") == horizon]
        horizons[horizon] = {
            "completed_broker_truth_sample_size": len(rows),
            "average_profit_capture_pct": _mean_optional([row.get("profit_capture_pct") for row in rows]),
            "average_profit_giveback_from_peak_pct": _mean_optional([row.get("profit_giveback_from_peak_pct") for row in rows]),
            "average_realized_return_per_day": _mean_optional([row.get("realized_return_per_day") for row in rows]),
            "average_realized_return_per_hour": _mean_optional([row.get("realized_return_per_hour") for row in rows]),
            "average_time_after_peak_seconds": _mean_optional([row.get("time_after_peak_seconds") for row in rows]),
        }
    shadow = dict(shadow_exit_performance or {})
    shadow_metrics = dict(shadow.get("metrics") or shadow.get("global") or {})
    sample = int(_to_float(shadow.get("sample_size"), 0))
    output_by_lifecycle = {
        _text(row.get("lifecycle_id")): row
        for row in list(dict(shadow_exit_outputs or {}).get("outputs") or [])
        if isinstance(row, dict) and _text(row.get("lifecycle_id"))
    }
    counterfactual_rows: list[dict[str, Any]] = []
    for row in official_rows:
        shadow_row = output_by_lifecycle.get(_text(row.get("lifecycle_id")))
        if not shadow_row:
            continue
        shadow_return = _first_number(shadow_row, "shadow_return_pct", "counterfactual_return_pct")
        actual_return = _optional_number(row.get("realized_return_pct"))
        if shadow_return is None or actual_return is None:
            continue
        counterfactual_rows.append({
            "lifecycle_id": row.get("lifecycle_id"), "actual_return_pct": actual_return,
            "shadow_return_pct": shadow_return, "return_difference_pct": round(shadow_return - actual_return, 6),
            "shadow_only": True, "execution_authority": "DISABLED", "promotion_status": "NOT_PROMOTED",
        })
    official_sample = len(official_rows)
    evidence_state = "SUFFICIENT_BROKER_TRUTH" if official_sample >= 3 else "INSUFFICIENT_BROKER_TRUTH_SAMPLE"
    summary = {
        "schema_version": TRADE_EFFECTIVENESS_V2_SCHEMA,
        "mode": "paper_only_observational_trade_effectiveness",
        "completed_broker_truth_sample_size": official_sample,
        "excluded_nonofficial_or_legacy_rows": excluded,
        "profitable_trade_count": sum((row.get("realized_return_pct") or 0.0) > 0 for row in official_rows),
        "losing_trade_count": sum((row.get("realized_return_pct") or 0.0) < 0 for row in official_rows),
        "average_profit_capture_pct": _mean_optional(captures),
        "median_profit_capture_pct": _median_optional(captures),
        "average_profit_giveback_from_peak_pct": _mean_optional(givebacks),
        "severe_giveback_count": sum(row.get("profit_capture_classification") == "SEVERE_GIVEBACK" for row in official_rows),
        "effective_exit_count": counts.get("EFFECTIVE", 0),
        "late_exit_count": counts.get("LATE", 0) + counts.get("SEVERE_PROFIT_GIVEBACK", 0),
        "effective_controlled_loss_count": counts.get("LOSS_ACCEPTANCE_EFFECTIVE", 0),
        "average_realized_return_per_day": _mean_optional(realized_per_day),
        "average_return_per_hour": _mean_optional(realized_per_hour),
        "median_return_per_hour": _median_optional(realized_per_hour),
        "average_time_after_peak_seconds": _mean_optional(after_peak),
        "top_success_drivers": [{"driver": key, "count": value} for key, value in success_drivers.most_common(5) if key != "UNAVAILABLE"],
        "top_failure_drivers": [{"driver": key, "count": value} for key, value in failure_drivers.most_common(5) if key != "UNAVAILABLE"],
        "controlled_loss_count": preventability_counts.get("CONTROLLED", 0),
        "preventable_loss_count": preventability_counts.get("PREVENTABLE", 0),
        "partly_preventable_loss_count": preventability_counts.get("PARTLY_PREVENTABLE", 0),
        "losses_not_proven_count": preventability_counts.get("NOT_PROVEN", 0),
        "loss_anatomy_counts": dict(loss_counts),
        "horizon_lane_breakdown": lanes,
        "horizon_breakdown": horizons,
        "shadow_exit_sample_size": sample,
        "shadow_outperformance_rate": shadow_metrics.get("shadow_win_rate") if sample else None,
        "shadow_evidence_state": "SHADOW_ONLY" if sample else "INSUFFICIENT_SHADOW_EVIDENCE",
        "counterfactual_exit_comparison_count": len(counterfactual_rows),
        "counterfactual_exit_comparisons": counterfactual_rows[:12],
        "evidence_sufficiency_state": evidence_state,
        "official_metrics_truth_tier": "BROKER_STRICT_TRUTH_ONLY",
        "shadow_metrics_never_promoted": True,
        "trade_rows": official_rows[-24:],
        "integrity_facts": integrity_facts[:12],
        "cortex_summary": {
            "completed_broker_truth_sample_size": official_sample,
            "average_profit_capture_pct": _mean_optional(captures),
            "average_profit_giveback_from_peak_pct": _mean_optional(givebacks),
            "late_exit_count": counts.get("LATE", 0) + counts.get("SEVERE_PROFIT_GIVEBACK", 0),
            "top_success_drivers": [{"driver": key, "count": value} for key, value in success_drivers.most_common(3) if key != "UNAVAILABLE"],
            "top_failure_drivers": [{"driver": key, "count": value} for key, value in failure_drivers.most_common(3) if key != "UNAVAILABLE"],
            "preventable_loss_count": preventability_counts.get("PREVENTABLE", 0),
            "controlled_loss_count": preventability_counts.get("CONTROLLED", 0),
            "average_return_per_hour": _mean_optional(realized_per_hour),
            "shadow_exit_sample_size": sample,
            "evidence_sufficiency_state": evidence_state,
            "advisory_only": True,
            "automatic_policy_promotion_allowed": False,
        },
        "provider_calls_used": 0,
        "broker_calls_used": 0,
        "llm_calls_used": 0,
        "full_history_scan_count": 0,
        "records_examined": len(bounded_truths),
        "execution_behavior_changed": False,
        "paper_only_preserved": True,
        "live_trading_changed": False,
        "advisory_only": True,
        "shadow_only": False,
        "shadow_components_only": True,
        "generated_at": _now_iso(),
    }
    return summary


class AdaptiveProfitCaptureIntelligenceV1:
    """Profit-capture learning derived from paper lifecycle evidence.

    This module is diagnostic-only. It never submits orders, closes positions,
    changes thresholds, or mutates broker state.
    """

    def __init__(self, state_dir: str = "state", ttl_seconds: float = 8.0) -> None:
        self.state_dir = str(state_dir or "state")
        self.v2_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v2.jsonl")
        self.v1_path = os.path.join(self.state_dir, "trade_lifecycle_excursion_v1.jsonl")
        self.state_path = os.path.join(self.state_dir, "adaptive_profit_capture_intelligence_v1.jsonl")
        self.ttl_seconds = float(ttl_seconds or 8.0)
        self._cache: dict[str, Any] | None = None
        self._cache_ts = 0.0
        self._last_write = 0.0

    def _latest_rows(self) -> list[dict[str, Any]]:
        latest: dict[str, dict[str, Any]] = {}
        for path in (self.v1_path, self.v2_path):
            for row in _tail_jsonl(path):
                lifecycle_id = _text(row.get("lifecycle_id"))
                if lifecycle_id:
                    latest[lifecycle_id] = row
        return list(latest.values())

    def _derive_row(self, row: dict[str, Any]) -> dict[str, Any] | None:
        lifecycle_id = _text(row.get("lifecycle_id"))
        symbol = _text(row.get("symbol")).upper()
        if not lifecycle_id or not symbol:
            return None
        closed = bool(row.get("closed"))
        peak = max(0.0, _to_float(row.get("peak_unrealized_profit_pct"), _to_float(row.get("max_favorable_excursion_pct"))))
        current_profit = _to_float(
            row.get("current_or_exit_profit_pct"),
            _to_float(row.get("current_return_pct"), _to_float(row.get("continuation_after_entry_pct"))),
        )
        missed = max(0.0, peak - current_profit)
        giveback = max(0.0, _to_float(row.get("profit_giveback_pct"), missed))
        capture_ratio = _to_float(row.get("profit_capture_ratio"), (max(0.0, current_profit) / peak if peak > 0 else 0.0))
        capture_ratio = max(0.0, min(1.0, capture_ratio))
        time_to_peak = _to_float(row.get("time_to_continuation_minutes"), _to_float(row.get("time_to_mfe_seconds")) / 60.0)
        hold_minutes = _to_float(row.get("hold_duration_minutes") or row.get("actual_hold_duration_minutes"))
        time_after_peak = max(0.0, hold_minutes - time_to_peak) if time_to_peak > 0 else 0.0
        decay_velocity = giveback / max(time_after_peak, hold_minutes, 1.0)
        retention_score = _clamp(capture_ratio * 100.0)
        penalty = min(35.0, giveback * 4.0) + min(20.0, decay_velocity * 50.0)
        quality = _clamp(retention_score - penalty + (10.0 if peak >= 1.0 and capture_ratio >= 0.6 else 0.0))
        label = _capture_label(capture_ratio, peak, closed)
        pattern = _giveback_pattern(row, peak, giveback, capture_ratio, time_to_peak)
        watch_label = _giveback_label(giveback, peak)
        continuation_healthy = _text(row.get("follow_through_label") or row.get("continuation_pattern_label")) in {
            "strong_continuation",
            "moderate_continuation",
            "strong_follow_through",
            "moderate_follow_through",
        }
        attention = 0.0 if closed else _clamp((giveback / max(peak, 0.25)) * 70.0 + max(0.0, -current_profit) * 8.0 + decay_velocity * 100.0)
        if not closed and continuation_healthy and attention < 35:
            watch_label = "continuation_still_healthy"
        reason = (
            "Active trade has meaningful peak profit and visible giveback."
            if not closed and attention >= 45
            else "Active trade remains under watch-only profit-capture learning."
            if not closed
            else f"Closed trade classified as {label}."
        )
        return {
            "enabled": True,
            "version": VERSION,
            "lifecycle_id": lifecycle_id,
            "symbol": symbol,
            "timestamp": _text(row.get("timestamp") or row.get("last_update_timestamp") or row.get("current_timestamp") or _now_iso()),
            "closed": closed,
            "peak_unrealized_profit_pct": _round(peak),
            "current_or_exit_profit_pct": _round(current_profit),
            "profit_capture_ratio": _round(capture_ratio, 4),
            "missed_profit_pct": _round(missed),
            "profit_giveback_pct": _round(giveback),
            "giveback_from_peak_pct": _round((giveback / peak) * 100.0 if peak > 0 else 0.0),
            "time_from_entry_to_peak_minutes": _round(time_to_peak, 2),
            "time_from_peak_to_giveback_minutes": _round(time_after_peak, 2),
            "profit_decay_velocity": _round(decay_velocity, 6),
            "profit_retention_score": _round(retention_score, 2),
            "profit_capture_quality_score": _round(quality, 2),
            "profit_capture_label": label,
            "giveback_severity_label": watch_label,
            "giveback_pattern": pattern,
            "current_unrealized_profit_pct": _round(current_profit),
            "current_giveback_pct": _round(giveback),
            "profit_protection_attention_score": _round(attention, 2),
            "continuation_still_healthy": bool(continuation_healthy),
            "profit_capture_watch_reason": reason,
            "sector": _text(row.get("sector"), "unknown"),
            "cap_tier": _text(row.get("cap_tier"), "unknown"),
            "trade_archetype": _text(row.get("trade_archetype"), "unknown"),
            "horizon_style": _text(row.get("horizon_style"), "unknown"),
            "market_regime": _text(row.get("market_regime"), "unknown"),
            "session_type": _text(row.get("session_type"), "unknown"),
            "allocation_lane": _text(row.get("allocation_lane"), "unknown"),
            "generated_at": _now_iso(),
            "api_calls_used": 0,
            "live_trading_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_exits_enabled": False,
        }

    def _write_rows(self, rows: list[dict[str, Any]]) -> None:
        now = time.time()
        if not rows or now - self._last_write < 45.0:
            return
        self._last_write = now
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "a", encoding="utf-8") as handle:
                for row in rows[-80:]:
                    handle.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
        except Exception:
            return

    @staticmethod
    def _avg(rows: list[dict[str, Any]], key: str) -> float | None:
        vals = [_to_float(row.get(key)) for row in rows if row.get(key) not in (None, "")]
        return round(mean(vals), 4) if vals else None

    @staticmethod
    def _group_average(rows: list[dict[str, Any]], group_key: str, value_key: str) -> dict[str, float]:
        grouped: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            key = _text(row.get(group_key), "unknown")
            if row.get(value_key) not in (None, ""):
                grouped[key].append(_to_float(row.get(value_key)))
        return {key: round(mean(values), 4) for key, values in grouped.items() if values}

    @staticmethod
    def _best_group(rows: list[dict[str, Any]], key: str, value_key: str, *, reverse: bool) -> str:
        grouped = AdaptiveProfitCaptureIntelligenceV1._group_average(rows, key, value_key)
        if not grouped:
            return "insufficient_data"
        return sorted(grouped.items(), key=lambda item: item[1], reverse=reverse)[0][0]

    def status(self, open_positions: list[dict[str, Any]] | None = None, *, force: bool = False) -> dict[str, Any]:
        start = time.perf_counter()
        now = time.time()
        if not force and self._cache is not None and now - self._cache_ts <= self.ttl_seconds:
            out = dict(self._cache)
            out["cache_hit"] = True
            out["cache_age_seconds"] = round(now - self._cache_ts, 3)
            out["build_ms"] = round((time.perf_counter() - start) * 1000.0, 3)
            return out

        derived = [row for row in (self._derive_row(raw) for raw in self._latest_rows()) if row]
        active_rows = [row for row in derived if not row.get("closed")]
        if open_positions is not None:
            active_symbols = {_text(row.get("symbol")).upper() for row in open_positions if isinstance(row, dict)}
            if active_symbols:
                active_rows = [row for row in active_rows if row.get("symbol") in active_symbols]
        active_by_symbol: dict[str, dict[str, Any]] = {}
        for row in active_rows:
            symbol = _text(row.get("symbol")).upper()
            previous = active_by_symbol.get(symbol)
            if not previous or _text(row.get("timestamp")) >= _text(previous.get("timestamp")):
                active_by_symbol[symbol] = row
        active = list(active_by_symbol.values())
        closed = [row for row in derived if row.get("closed")]
        summary_rows = active + closed
        self._write_rows(summary_rows)

        capture_dist = Counter(_text(row.get("profit_capture_label"), "insufficient_data") for row in summary_rows)
        pattern_counts = Counter(_text(row.get("giveback_pattern"), "unknown") for row in summary_rows)
        high_giveback = [
            row for row in summary_rows
            if _text(row.get("profit_capture_label")) in {"weak_capture", "severe_giveback"}
            or _text(row.get("giveback_severity_label")) in {"profit_capture_watch", "high_giveback_watch"}
        ]
        open_watchlist = [
            {
                "symbol": row.get("symbol"),
                "current_unrealized_profit_pct": row.get("current_unrealized_profit_pct"),
                "peak_unrealized_profit_pct": row.get("peak_unrealized_profit_pct"),
                "current_giveback_pct": row.get("current_giveback_pct"),
                "giveback_severity_label": row.get("giveback_severity_label"),
                "profit_protection_attention_score": row.get("profit_protection_attention_score"),
                "continuation_still_healthy": row.get("continuation_still_healthy"),
                "profit_capture_watch_reason": row.get("profit_capture_watch_reason"),
            }
            for row in sorted(active, key=lambda item: _to_float(item.get("profit_protection_attention_score")), reverse=True)[:12]
        ]
        avg_capture = self._avg(summary_rows, "profit_capture_ratio")
        avg_giveback = self._avg(summary_rows, "profit_giveback_pct")
        avg_missed = self._avg(summary_rows, "missed_profit_pct")
        avg_retention = self._avg(summary_rows, "profit_retention_score")
        avg_quality = self._avg(summary_rows, "profit_capture_quality_score")
        worst_symbol = max(summary_rows, key=lambda row: _to_float(row.get("profit_giveback_pct")), default={}).get("symbol", "insufficient_data")
        recommendation = "insufficient_data"
        reason = "Waiting for more lifecycle profit-capture evidence."
        if len(summary_rows) >= 5:
            if len(high_giveback) >= max(2, int(len(summary_rows) * 0.25)):
                recommendation = "monitor_peak_decay_for_context"
                reason = "Meaningful peak profits are being surrendered often enough to require watch-only review."
            elif (avg_capture or 0.0) < 0.45:
                recommendation = "improve_continuation_confirmation"
                reason = "Average retained profit is below the acceptable capture band."
            elif (avg_capture or 0.0) >= 0.65:
                recommendation = "allow_more_patience_for_context"
                reason = "Profit capture is holding up in current evidence; avoid overreactive future tuning."
            else:
                recommendation = "tighten_profit_review_for_context"
                reason = "Capture is acceptable but giveback remains visible; keep shadow review focused."

        out = {
            "enabled": True,
            "version": VERSION,
            "mode": "paper_only_profit_capture_learning",
            "tracked_lifecycles": len(summary_rows),
            "active_trades_reviewed": len(active),
            "closed_trades_reviewed": len(closed),
            "average_profit_capture_ratio": avg_capture,
            "average_profit_giveback_pct": avg_giveback,
            "average_missed_profit_pct": avg_missed,
            "average_profit_retention_score": avg_retention,
            "profit_capture_quality_score": avg_quality,
            "high_giveback_trade_count": len(high_giveback),
            "excellent_capture_count": int(capture_dist.get("excellent_capture", 0)),
            "weak_capture_count": int(capture_dist.get("weak_capture", 0)),
            "severe_giveback_count": int(capture_dist.get("severe_giveback", 0)),
            "profit_capture_label_distribution": dict(capture_dist),
            "best_profit_capture_context": self._best_group(summary_rows, "sector", "profit_capture_ratio", reverse=True),
            "weakest_profit_capture_context": self._best_group(summary_rows, "sector", "profit_capture_ratio", reverse=False),
            "best_profit_capture_symbol": self._best_group(summary_rows, "symbol", "profit_capture_ratio", reverse=True),
            "worst_profit_capture_symbol": self._best_group(summary_rows, "symbol", "profit_capture_ratio", reverse=False),
            "best_profit_capture_archetype": self._best_group(summary_rows, "trade_archetype", "profit_capture_ratio", reverse=True),
            "worst_profit_capture_archetype": self._best_group(summary_rows, "trade_archetype", "profit_capture_ratio", reverse=False),
            "worst_giveback_symbol": worst_symbol,
            "top_giveback_patterns": dict(pattern_counts.most_common(6)),
            "most_common_giveback_pattern": pattern_counts.most_common(1)[0][0] if pattern_counts else "insufficient_data",
            "high_giveback_symbols": [row.get("symbol") for row in sorted(high_giveback, key=lambda item: _to_float(item.get("profit_giveback_pct")), reverse=True)[:8]],
            "high_giveback_archetypes": dict(Counter(_text(row.get("trade_archetype"), "unknown") for row in high_giveback).most_common(6)),
            "high_giveback_contexts": dict(Counter(_context_key(row) for row in high_giveback).most_common(6)),
            "profit_capture_by_horizon": self._group_average(summary_rows, "horizon_style", "profit_capture_ratio"),
            "profit_capture_by_regime": self._group_average(summary_rows, "market_regime", "profit_capture_ratio"),
            "profit_capture_by_sector": self._group_average(summary_rows, "sector", "profit_capture_ratio"),
            "open_position_watchlist": open_watchlist,
            "open_position_watchlist_count": len(open_watchlist),
            "profit_capture_recommendation": recommendation,
            "profit_capture_reason": reason,
            "human_review_required": True,
            "auto_apply_allowed": False,
            "summary": (
                f"Reviewed {len(summary_rows)} paper lifecycles for profit retention, giveback, and peak-decay behavior."
            ),
            "api_calls_used": 0,
            "cache_hit": False,
            "cache_age_seconds": 0.0,
            "build_ms": round((time.perf_counter() - start) * 1000.0, 3),
            "live_trading_changed": False,
            "broker_behavior_changed": False,
            "alpaca_paper_only_preserved": True,
            "natural_exit_preserved": True,
            "forced_trades_enabled": False,
            "forced_exits_enabled": False,
        }
        self._cache = dict(out)
        self._cache_ts = now
        return out
