"""Profit protection, peak-gain preservation, and giveback control.

This module is strictly advisory/shadow-only. It evaluates profitable positions
for excessive giveback and produces canonical position-level advisory
assessments. It consumes loss-containment facts when available and never
submits or authorizes broker orders.

Policy version: astra_profit_protection_giveback_policy_v1
Engine version: astra_profit_protection_giveback_v1
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from engine.astra_canonical_market_timestamp_v1 import canonical_market_timestamp_v1


POLICY_SCHEMA_VERSION = "astra_profit_protection_giveback_policy_v1"
ENGINE_SCHEMA_VERSION = "astra_profit_protection_giveback_v1"
OUTPUT_SCHEMA_VERSION = "astra_profit_protection_decision_envelope_v1"


# Provisional lane-aware giveback policy candidates.
# These are initial paper-policy candidates, not proven optimal parameters.
# Bands are expressed as fractions of peak profit given back.
LANE_GIVEBACK_BANDS: dict[str, dict[str, float]] = {
    "DAY": {
        "early_watch_ratio": 0.25,
        "protect_profit_ratio": 0.40,
        "exit_review_ratio": 0.60,
        "minimum_retained_gain_pct": 0.3,
    },
    "CRYPTO": {
        "early_watch_ratio": 0.30,
        "protect_profit_ratio": 0.45,
        "exit_review_ratio": 0.60,
        "minimum_retained_gain_pct": 0.5,
    },
    "SWING": {
        "early_watch_ratio": 0.35,
        "protect_profit_ratio": 0.50,
        "exit_review_ratio": 0.60,
        "minimum_retained_gain_pct": 0.4,
    },
}

# Minimum peak gain required before profit-protection monitoring is meaningful.
MIN_PEAK_GAIN_PCT = 0.5

# Staleness tolerance for critical price evidence (minutes).
DEFAULT_PRICE_STALENESS_MINUTES = 15.0


PROFIT_PROTECTION_STATES = frozenset({
    "NO_PROFIT_HISTORY",
    "PROFIT_HEALTHY",
    "PROFIT_WATCH",
    "GIVEBACK_ELEVATED",
    "PROTECT_PROFIT",
    "EXIT_REVIEW",
    "THESIS_BROKEN",
    "LOSS_CONTAINMENT_PRIORITY",
    "DATA_INCOMPLETE_FAIL_CLOSED",
    "UNRESOLVED_FAIL_CLOSED",
})

PROFIT_PROTECTION_RECOMMENDATIONS = frozenset({
    "HOLD",
    "WATCH",
    "PROTECT_PROFIT",
    "TIGHTEN_REVIEW",
    "EXIT_REVIEW",
    "THESIS_BROKEN",
    "DEFER_TO_LOSS_CONTAINMENT",
    "DATA_INCOMPLETE_FAIL_CLOSED",
})


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    return _num(value, default) or default


def _lane(value: Any) -> str:
    lane = _text(value).upper()
    if lane in {"DAY", "SWING", "CRYPTO"}:
        return lane
    return ""


def _age_minutes(value: Any, now: datetime | None = None) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        ref = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        return max(0.0, (ref - dt).total_seconds() / 60.0)
    except Exception:
        return None


def _decision_identity(position_id: str, symbol: str, lane: str, as_of: str, recommendation: str) -> str:
    symbol = _text(symbol).upper()
    lane = _lane(lane)
    seed = f"pp|{position_id}|{symbol}|{lane}|{recommendation}|{as_of[:19]}"
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _event_identity(position_id: str, symbol: str, lane: str, as_of: str, event_type: str) -> str:
    symbol = _text(symbol).upper()
    lane = _lane(lane)
    seed = f"pp_event|{position_id}|{symbol}|{lane}|{event_type}|{as_of[:19]}"
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=True)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _load_json(path: str, default: dict[str, Any] | None = None) -> dict[str, Any]:
    default = dict(default or {})
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return default


def load_profit_protection_state_v1(path: str) -> dict[str, Any]:
    """Load prior profit-protection state; malformed files fail closed."""
    raw = _load_json(path)
    if not raw:
        return {
            "schema_version": "astra_profit_protection_state_v1",
            "loaded": False,
            "forensic": None,
            "decisions": {},
            "events": {},
            "as_of": _iso(),
        }
    if not isinstance(raw, dict):
        return {
            "schema_version": "astra_profit_protection_state_v1",
            "loaded": False,
            "forensic": {
                "error": "top_level_not_a_dict",
                "type": str(type(raw)),
            },
            "decisions": {},
            "events": {},
            "as_of": _iso(),
        }
    base = {
        "schema_version": "astra_profit_protection_state_v1",
        "loaded": True,
        "forensic": None,
        "decisions": dict(raw.get("decisions") or {}),
        "events": dict(raw.get("events") or {}),
        "as_of": _iso(),
    }
    # Preserve phase-level metadata written by the review phase.
    for key in (
        "broker_fetch_succeeded",
        "position_truth_available",
        "observation_state",
        "confirmed_open_position_count",
        "first_phase_blocker",
    ):
        if key in raw:
            base[key] = raw[key]
    return base


def save_profit_protection_state_v1(path: str, state: Mapping[str, Any]) -> None:
    """Persist profit-protection state atomically."""
    payload = {
        "schema_version": "astra_profit_protection_state_v1",
        "decisions": dict(state.get("decisions") or {}),
        "events": dict(state.get("events") or {}),
        "as_of": _iso(),
    }
    # Preserve phase-level metadata written by the review phase.
    for key in (
        "broker_fetch_succeeded",
        "position_truth_available",
        "observation_state",
        "confirmed_open_position_count",
        "first_phase_blocker",
    ):
        if key in state:
            payload[key] = state[key]
    _atomic_write_json(path, payload)


def _resolve_position_inputs(
    position: Mapping[str, Any],
    broker_position: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve canonical inputs for profit protection from approved sources."""
    pos = dict(position or {})
    broker = dict(broker_position or {})

    symbol = _text(
        pos.get("symbol") or broker.get("symbol")
    ).upper()
    position_id = _text(
        pos.get("position_id") or pos.get("asset_id") or broker.get("id") or broker.get("asset_id") or symbol
    )

    # When recovery returns UNAVAILABLE and no broker lane exists, the engine
    # derives an *effective_lane* from asset_class for threshold rails only.
    # The *historical_lane* remains UNKNOWN — management policy is not ownership.
    recovery_present = "lane_recovery_status" in pos
    lane_recovery_unavailable = recovery_present and _text(pos.get("lane_recovery_status")).upper() == "UNAVAILABLE"
    lane = _lane(pos.get("lane_id"))
    historical_lane = lane if lane else "UNKNOWN"
    derived_lane = False
    management_policy = "NONE"

    explicit_lane = _text(pos.get("lane_id")).upper()
    if not lane and explicit_lane:
        if explicit_lane == "SCALP":
            lane = "DAY"
        else:
            lane = explicit_lane
        historical_lane = lane

    if not lane and (not recovery_present or lane_recovery_unavailable):
        asset_class = _text(
            pos.get("asset_class") or pos.get("asset_type") or broker.get("asset_class") or broker.get("asset_type")
        ).lower()
        if asset_class in {"crypto", "cryptocurrency"}:
            lane = "CRYPTO"
            management_policy = "LEGACY_CRYPTO_RECOVERY"
        elif asset_class in {"equity", "stock", "us_equity", "etf"}:
            lane = "SWING"
            management_policy = "LEGACY_EQUITY_RECOVERY"
        derived_lane = bool(lane) and historical_lane == "UNKNOWN"
    if not lane and not recovery_present:
        horizon = _text(
            pos.get("paper_entry_horizon_style")
            or pos.get("trade_horizon_style")
            or pos.get("intended_horizon")
            or pos.get("original_horizon")
        ).lower()
        if horizon in {"scalp", "day_trade", "day", "intraday", "daytrading"}:
            lane = "DAY"
        elif horizon in {"swing_trade", "swing", "position_trade", "position"}:
            lane = "SWING"

    if lane and not derived_lane and historical_lane == "UNKNOWN":
        historical_lane = lane

    quantity = abs(
        _num(broker.get("qty")) or _num(broker.get("qty_available"))
        or _num(pos.get("qty")) or _num(pos.get("quantity")) or 0.0
    )

    entry_price = (
        _num(broker.get("avg_entry_price")) or _num(pos.get("avg_entry_price"))
        or _num(pos.get("entry_price")) or _num(pos.get("cost_basis")) or 0.0
    )

    current_price = (
        _num(broker.get("current_price")) or _num(broker.get("market_price"))
        or _num(broker.get("lastday_price")) or _num(pos.get("current_price"))
        or _num(pos.get("last_price")) or _num(pos.get("market_price")) or 0.0
    )

    market_value = (
        _num(broker.get("market_value")) or _num(pos.get("market_value"))
        or (quantity * current_price if quantity > 0 and current_price > 0 else 0.0)
    )
    cost_basis = (
        _num(pos.get("cost_basis")) or (entry_price * quantity if entry_price > 0 and quantity > 0 else 0.0)
    )

    unrealized_pl_pct = _num(
        pos.get("unrealized_plpc") or pos.get("unrealized_return_pct") or pos.get("unrealized_pct")
    )
    if unrealized_pl_pct is None and cost_basis > 0 and market_value > 0:
        unrealized_pl_pct = ((market_value - cost_basis) / cost_basis) * 100.0
    if unrealized_pl_pct is None:
        unrealized_pl_pct = 0.0

    unrealized_pl_dollars = (
        _num(pos.get("unrealized_pl")) or _num(pos.get("unrealized_pnl"))
        or (market_value - cost_basis if market_value > 0 and cost_basis > 0 else 0.0)
    )

    # Peak gain evidence: do not infer from current price alone.
    peak_unrealized_pct = _num(
        pos.get("peak_unrealized_gain_pct") or pos.get("max_favorable_excursion_pct") or pos.get("mfe_pct")
    )
    peak_unrealized_dollars = _num(
        pos.get("peak_unrealized_gain_dollars") or pos.get("peak_unrealized_pl_dollars")
    )
    peak_price = _num(pos.get("peak_price") or pos.get("high_since_entry"))
    if peak_price is None and peak_unrealized_pct is not None and entry_price > 0:
        peak_price = entry_price * (1.0 + peak_unrealized_pct / 100.0)

    mae_pct = _num(pos.get("max_adverse_excursion_pct") or pos.get("mae_pct"))

    retrieval_timestamp = _text(broker.get("retrieval_timestamp") or broker.get("retrieved_at") or broker.get("fetched_at"))
    provider_native_ts = canonical_market_timestamp_v1(
        {
            **pos,
            **broker,
            "observation_timestamp": broker.get("observation_timestamp")
            or pos.get("observation_timestamp"),
            "market_timestamp": broker.get("market_timestamp")
            or pos.get("market_timestamp"),
            "quote_timestamp": broker.get("quote_timestamp") or pos.get("quote_timestamp"),
            "trade_timestamp": broker.get("trade_timestamp") or pos.get("trade_timestamp"),
            "retrieval_timestamp": retrieval_timestamp,
        },
        source_type="QUOTE" if (broker.get("quote_timestamp") or pos.get("quote_timestamp")) else None,
    )
    provider_native_timestamp = provider_native_ts["provider_native_timestamp"]
    provider_native_timestamp_provenance = provider_native_ts["provenance"]
    provider_native_timestamp_source = provider_native_ts["source_field"]
    price_timestamp = provider_native_ts["market_observation_timestamp"]

    holding_minutes = _age_minutes(
        pos.get("entry_timestamp") or pos.get("entry_filled_at") or pos.get("created_at")
    )
    time_since_peak_minutes = _age_minutes(
        pos.get("peak_timestamp") or pos.get("peak_unrealized_gain_at")
    )

    return {
        "position_id": position_id,
        "symbol": symbol,
        "lane": lane,
        "historical_lane": historical_lane,
        "effective_lane": lane,
        "management_policy": management_policy,
        "lane_derived_from_asset_class": derived_lane,
        "quantity": quantity,
        "entry_price": entry_price,
        "current_price": current_price,
        "market_value": market_value,
        "cost_basis": cost_basis,
        "unrealized_pl_pct": unrealized_pl_pct,
        "unrealized_pl_dollars": unrealized_pl_dollars,
        "peak_unrealized_pct": peak_unrealized_pct,
        "peak_unrealized_dollars": peak_unrealized_dollars,
        "peak_price": peak_price,
        "mae_pct": mae_pct,
        "price_timestamp": price_timestamp,
        "market_observation_timestamp": provider_native_ts["market_observation_timestamp"],
        "retrieval_timestamp": retrieval_timestamp,
        "market_observation_unavailable": bool(provider_native_ts["market_observation_unavailable"]),
        "market_timestamp_contract": provider_native_ts,
        "provider_native_timestamp": provider_native_timestamp,
        "provider_native_timestamp_provenance": provider_native_timestamp_provenance,
        "provider_native_timestamp_source": provider_native_timestamp_source,
        "holding_minutes": holding_minutes,
        "time_since_peak_minutes": time_since_peak_minutes,
        "horizon": _text(pos.get("paper_entry_horizon_style") or pos.get("horizon")),
        "lane_recovery_status": _text(pos.get("lane_recovery_status")),
        "horizon_recovery_status": _text(pos.get("horizon_recovery_status")),
        "lane_source": _text(pos.get("lane_source")),
        "horizon_source": _text(pos.get("horizon_source")),
        "recovery_method": _text(pos.get("recovery_method")),
        "recovery_exact_blockers": list(pos.get("recovery_exact_blockers") or []),
    }


def _validate_inputs(
    inputs: dict[str, Any],
    policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> list[str]:
    blockers: list[str] = []
    if not inputs.get("position_id"):
        blockers.append("MISSING_POSITION_ID")
    if not inputs.get("symbol"):
        blockers.append("MISSING_SYMBOL")

    lane = inputs.get("lane")
    recovery_present = bool(inputs.get("lane_recovery_status"))
    if lane:
        if lane not in LANE_GIVEBACK_BANDS:
            blockers.append(f"UNKNOWN_LANE:{lane}")
    elif recovery_present:
        blockers.extend(str(item) for item in inputs.get("recovery_exact_blockers") or [] if str(item))
    else:
        blockers.append("MISSING_LANE")
    if recovery_present and inputs.get("horizon_recovery_status") != "RESOLVED":
        # Horizon recovery unavailable is advisory for profit protection.
        # The engine can still evaluate profit rails against lane bands.
        # Consumers must check horizon_recovery_status for exit decisions.
        pass
    blockers = list(dict.fromkeys(blockers))

    if inputs.get("entry_price", 0.0) <= 0.0:
        blockers.append("MISSING_OR_INVALID_ENTRY_PRICE")
    if inputs.get("current_price", 0.0) <= 0.0:
        blockers.append("MISSING_OR_INVALID_CURRENT_PRICE")
    if inputs.get("quantity", 0.0) <= 0.0:
        blockers.append("MISSING_OR_INVALID_QUANTITY")

    price_ts = inputs.get("market_observation_timestamp") or inputs.get("price_timestamp")
    if inputs.get("market_observation_unavailable"):
        blockers.append("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE")
    elif price_ts:
        age = _age_minutes(price_ts, now)
        if age is None:
            blockers.append("PRICE_TIMESTAMP_UNPARSEABLE")
        else:
            staleness = float((policy or {}).get("price_staleness_minutes", DEFAULT_PRICE_STALENESS_MINUTES))
            if age > staleness:
                blockers.append(f"PRICE_STALE:{round(age, 2)}min_exceeds_{staleness}min")
    else:
        blockers.append("MISSING_PRICE_TIMESTAMP")

    peak = inputs.get("peak_unrealized_pct")
    if peak is None and inputs.get("peak_unrealized_dollars") is None and inputs.get("peak_price") is None:
        # Missing peak evidence is not a hard blocker; it produces NO_PROFIT_HISTORY.
        pass
    if peak is not None and peak < MIN_PEAK_GAIN_PCT:
        blockers.append(f"PEAK_GAIN_BELOW_MONITORING_THRESHOLD:{peak}")

    return blockers


def _get_giveback_bands(lane: str, policy_override: Mapping[str, Any] | None = None) -> dict[str, float]:
    override = dict(policy_override or {}).get("lane_giveback_bands", {})
    defaults = dict(LANE_GIVEBACK_BANDS.get(lane, {}))
    lane_override = dict(override.get(lane, {}))
    return {
        "early_watch_ratio": float(lane_override.get("early_watch_ratio", defaults.get("early_watch_ratio", 0.30))),
        "protect_profit_ratio": float(lane_override.get("protect_profit_ratio", defaults.get("protect_profit_ratio", 0.45))),
        "exit_review_ratio": float(lane_override.get("exit_review_ratio", defaults.get("exit_review_ratio", 0.60))),
        "minimum_retained_gain_pct": float(lane_override.get("minimum_retained_gain_pct", defaults.get("minimum_retained_gain_pct", 0.40))),
    }


def _calculate_profit_metrics(inputs: dict[str, Any]) -> dict[str, Any]:
    """Compute peak, current, giveback, capture, and retained metrics."""
    entry_price = inputs.get("entry_price", 0.0)
    current_price = inputs.get("current_price", 0.0)
    current_return_pct = inputs.get("unrealized_pl_pct", 0.0)
    current_return_dollars = inputs.get("unrealized_pl_dollars", 0.0)

    peak_unrealized_pct = inputs.get("peak_unrealized_pct")
    peak_unrealized_dollars = inputs.get("peak_unrealized_dollars")
    peak_price = inputs.get("peak_price")

    # If only peak dollars available, derive peak percent.
    if peak_unrealized_pct is None and peak_unrealized_dollars is not None and inputs.get("cost_basis", 0.0) > 0:
        peak_unrealized_pct = (peak_unrealized_dollars / inputs["cost_basis"]) * 100.0

    # If only peak price available, derive peak percent.
    if peak_unrealized_pct is None and peak_price is not None and entry_price > 0:
        peak_unrealized_pct = ((peak_price - entry_price) / entry_price) * 100.0

    has_peak = peak_unrealized_pct is not None and peak_unrealized_pct >= MIN_PEAK_GAIN_PCT

    if not has_peak:
        return {
            "peak_gain_pct": None,
            "current_return_pct": current_return_pct,
            "giveback_pct_points": None,
            "giveback_ratio": None,
            "capture_ratio": None,
            "retained_profit_pct": None,
            "retained_profit_dollars": current_return_dollars,
            "peak_evidence_available": False,
            "peak_evidence_reason": "peak_unrealized_gain_evidence_missing_or_below_threshold",
        }

    peak_gain_pct = float(peak_unrealized_pct)
    giveback_pct_points = peak_gain_pct - current_return_pct
    giveback_ratio = (giveback_pct_points / peak_gain_pct) if peak_gain_pct > 0 else None
    capture_ratio = (current_return_pct / peak_gain_pct) if peak_gain_pct > 0 else None
    retained_profit_pct = current_return_pct if current_return_pct > 0 else 0.0

    return {
        "peak_gain_pct": peak_gain_pct,
        "current_return_pct": current_return_pct,
        "giveback_pct_points": giveback_pct_points,
        "giveback_ratio": giveback_ratio,
        "capture_ratio": capture_ratio,
        "retained_profit_pct": retained_profit_pct,
        "retained_profit_dollars": max(0.0, current_return_dollars),
        "peak_evidence_available": True,
        "peak_evidence_reason": "canonical_peak_unrealized_gain_available",
    }


def _evaluate_thesis_state(position: Mapping[str, Any]) -> dict[str, Any]:
    pos = dict(position or {})
    broken_signals: list[str] = []
    intact_signals: list[str] = []

    if pos.get("thesis") or pos.get("intelligence_summary"):
        intact_signals.append("thesis_summary_present")
    if pos.get("thesis_supporting_conditions"):
        intact_signals.append("support_conditions_defined")
    if pos.get("thesis_invalidation_conditions"):
        intact_signals.append("invalidation_conditions_defined")
    if pos.get("catalyst_state") or pos.get("catalyst_context_label"):
        intact_signals.append("catalyst_state_present")

    if bool(pos.get("thesis_broken") or pos.get("thesis_invalidated") or pos.get("setup_failed")):
        broken_signals.append("explicit_thesis_broken_flag")

    if broken_signals:
        return {
            "thesis_state": "THESIS_BROKEN",
            "thesis_confidence": 0.85,
            "thesis_reason": "explicit_thesis_failure",
            "thesis_broken_signals": broken_signals,
            "thesis_intact_signals": intact_signals,
        }
    if not intact_signals:
        return {
            "thesis_state": "THESIS_UNKNOWN",
            "thesis_confidence": 0.5,
            "thesis_reason": "insufficient_thesis_evidence",
            "thesis_broken_signals": [],
            "thesis_intact_signals": [],
        }
    return {
        "thesis_state": "THESIS_INTACT",
        "thesis_confidence": 0.65,
        "thesis_reason": "thesis_evidence_present_no_failure_signals",
        "thesis_broken_signals": [],
        "thesis_intact_signals": intact_signals,
    }


def _evaluate_momentum_state(position: Mapping[str, Any], metrics: Mapping[str, Any]) -> dict[str, Any]:
    pos = dict(position or {})
    label = _text(pos.get("momentum_state") or pos.get("trend_state")).upper()
    improving: list[str] = []
    deteriorating: list[str] = []

    if label in {"IMPROVING", "BULLISH", "STRENGTHENING", "RECOVERING"}:
        improving.append("momentum_label_improving")
    elif label in {"DETERIORATING", "BEARISH", "WEAKENING", "FADING"}:
        deteriorating.append("momentum_label_deteriorating")
    elif label:
        improving.append("momentum_label_present")

    # Giveback-based momentum deterioration.
    giveback_ratio = metrics.get("giveback_ratio")
    if giveback_ratio is not None and giveback_ratio > 0.5:
        deteriorating.append("giveback_exceeded_50pct_of_peak")
    elif giveback_ratio is not None and giveback_ratio > 0.3:
        deteriorating.append("giveback_exceeded_30pct_of_peak")

    # Support and catalyst failures are treated as deterioration signals for
    # profit protection, not as automatic thesis breaks.
    if bool(pos.get("support_failed") or pos.get("support_broken") or pos.get("key_support_violated")):
        deteriorating.append("support_failure")
    if bool(pos.get("catalyst_invalidated") or pos.get("catalyst_expired") or pos.get("catalyst_failed")):
        deteriorating.append("catalyst_invalidated")

    if deteriorating:
        return {
            "momentum_state": "DETERIORATING",
            "momentum_confidence": 0.65,
            "momentum_reason": "momentum_signals_deteriorating",
            "improving_signals": improving,
            "deteriorating_signals": deteriorating,
        }
    if improving:
        return {
            "momentum_state": "IMPROVING",
            "momentum_confidence": 0.6,
            "momentum_reason": "momentum_signals_improving",
            "improving_signals": improving,
            "deteriorating_signals": deteriorating,
        }
    return {
        "momentum_state": "UNKNOWN",
        "momentum_confidence": 0.5,
        "momentum_reason": "no_momentum_evidence",
        "improving_signals": [],
        "deteriorating_signals": [],
    }


def _evaluate_continuation_confidence(
    position: Mapping[str, Any],
    metrics: Mapping[str, Any],
    thesis: Mapping[str, Any],
    momentum: Mapping[str, Any],
) -> dict[str, Any]:
    pos = dict(position or {})
    score = 0.5
    reasons: list[str] = []

    if thesis.get("thesis_state") == "THESIS_INTACT":
        score += 0.15
        reasons.append("thesis_intact")
    if momentum.get("momentum_state") in {"IMPROVING", "UNKNOWN"}:
        score += 0.10
        reasons.append("momentum_stable_or_improving")
    if not bool(pos.get("support_failed") or pos.get("support_broken")):
        score += 0.10
        reasons.append("support_not_failed")
    if not bool(pos.get("catalyst_invalidated") or pos.get("catalyst_expired")):
        score += 0.10
        reasons.append("catalyst_not_invalidated")

    giveback_ratio = metrics.get("giveback_ratio")
    if giveback_ratio is not None and giveback_ratio < 0.25:
        score += 0.10
        reasons.append("giveback_within_low_band")
    elif giveback_ratio is not None and giveback_ratio > 0.50:
        score -= 0.20
        reasons.append("giveback_excessive")

    if bool(pos.get("replacement_candidate_better") or pos.get("superior_replacement_available")):
        score -= 0.15
        reasons.append("superior_replacement_available")

    score = max(0.0, min(1.0, score))
    return {
        "continuation_confidence": round(score, 4),
        "continuation_confidence_reasons": reasons,
    }


def _evaluate_loss_containment_priority(
    loss_containment_decision: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Determine if loss containment overrides profit protection."""
    lc = dict(loss_containment_decision or {})
    threshold_state = _text(lc.get("threshold_state")).upper()
    recommendation = _text(lc.get("canonical_recommendation")).upper()

    priority_states = {
        "HARD_BOUNDARY_BREACH",
        "THESIS_BROKEN",
        "MANDATORY_REVIEW",
        "DATA_INCOMPLETE_FAIL_CLOSED",
        "UNRESOLVED_FAIL_CLOSED",
    }
    priority_recommendations = {
        "HARD_LOSS_EXIT_REQUIRED_ADVISORY",
        "THESIS_BROKEN",
        "EXIT_REVIEW",
        "DATA_INCOMPLETE_FAIL_CLOSED",
    }

    if threshold_state in priority_states or recommendation in priority_recommendations:
        return {
            "loss_containment_priority": True,
            "loss_containment_state": threshold_state or recommendation or "UNKNOWN",
            "loss_containment_reason": "loss_containment_recommendation_takes_precedence",
        }
    return {
        "loss_containment_priority": False,
        "loss_containment_state": threshold_state or "UNKNOWN",
        "loss_containment_reason": "no_loss_containment_priority_signal",
    }


def _derive_state_and_recommendation(
    metrics: Mapping[str, Any],
    bands: Mapping[str, float],
    thesis: Mapping[str, Any],
    momentum: Mapping[str, Any],
    continuation: Mapping[str, Any],
    loss_containment: Mapping[str, Any],
    blockers: Sequence[str],
) -> tuple[str, str, list[str]]:
    if blockers:
        return "DATA_INCOMPLETE_FAIL_CLOSED", "DATA_INCOMPLETE_FAIL_CLOSED", ["critical_evidence_incomplete:" + ";".join(blockers)]

    if loss_containment.get("loss_containment_priority"):
        return "LOSS_CONTAINMENT_PRIORITY", "DEFER_TO_LOSS_CONTAINMENT", [loss_containment.get("loss_containment_reason") or "loss_containment_priority"]

    if thesis.get("thesis_state") == "THESIS_BROKEN":
        return "THESIS_BROKEN", "THESIS_BROKEN", ["thesis_broken_overrides_profit_logic"]

    if not metrics.get("peak_evidence_available"):
        return "NO_PROFIT_HISTORY", "HOLD", ["no_canonical_peak_gain_evidence"]

    current_return_pct = metrics.get("current_return_pct", 0.0)
    if current_return_pct <= 0.0:
        return "EXIT_REVIEW", "EXIT_REVIEW", ["current_position_not_profitable_after_peak"]

    giveback_ratio = metrics.get("giveback_ratio")
    if giveback_ratio is None:
        return "DATA_INCOMPLETE_FAIL_CLOSED", "DATA_INCOMPLETE_FAIL_CLOSED", ["giveback_ratio_uncomputable"]

    retained_floor = bands.get("minimum_retained_gain_pct", 0.0)
    if current_return_pct < retained_floor:
        return "EXIT_REVIEW", "EXIT_REVIEW", [f"current_return_{current_return_pct:.4f}_below_retained_floor_{retained_floor}"]

    if giveback_ratio >= bands.get("exit_review_ratio", 0.60):
        return "EXIT_REVIEW", "EXIT_REVIEW", [f"giveback_ratio_{giveback_ratio:.4f}_exceeds_exit_review_band"]

    if giveback_ratio >= bands.get("protect_profit_ratio", 0.45):
        return "PROTECT_PROFIT", "PROTECT_PROFIT", [f"giveback_ratio_{giveback_ratio:.4f}_exceeds_protect_profit_band"]

    if giveback_ratio >= bands.get("early_watch_ratio", 0.30):
        if momentum.get("momentum_state") == "DETERIORATING":
            return "GIVEBACK_ELEVATED", "TIGHTEN_REVIEW", ["giveback_elevated_and_momentum_deteriorating"]
        return "PROFIT_WATCH", "WATCH", [f"giveback_ratio_{giveback_ratio:.4f}_in_early_watch_band"]

    # Healthy profit with credible continuation.
    if continuation.get("continuation_confidence", 0.0) >= 0.7:
        return "PROFIT_HEALTHY", "HOLD", ["profit_healthy_with_credible_continuation"]
    return "PROFIT_HEALTHY", "WATCH", ["profit_healthy_low_continuation_confidence"]


def _build_shadow_record(
    inputs: dict[str, Any],
    metrics: dict[str, Any],
    state: str,
    recommendation: str,
    thesis: Mapping[str, Any],
    momentum: Mapping[str, Any],
    continuation: Mapping[str, Any],
    loss_containment: Mapping[str, Any],
    as_of: str,
) -> dict[str, Any]:
    return {
        "position_id": inputs.get("position_id"),
        "symbol": inputs.get("symbol"),
        "lane": inputs.get("lane"),
        "recommendation_timestamp": as_of,
        "entry_price": inputs.get("entry_price"),
        "current_price": inputs.get("current_price"),
        "peak_price": inputs.get("peak_price"),
        "peak_gain_pct": metrics.get("peak_gain_pct"),
        "current_return_pct": metrics.get("current_return_pct"),
        "giveback_pct_points": metrics.get("giveback_pct_points"),
        "giveback_ratio": metrics.get("giveback_ratio"),
        "capture_ratio": metrics.get("capture_ratio"),
        "advisory_recommendation": recommendation,
        "profit_state": state,
        "thesis_state": thesis.get("thesis_state"),
        "momentum_state": momentum.get("momentum_state"),
        "continuation_confidence": continuation.get("continuation_confidence"),
        "loss_containment_priority": loss_containment.get("loss_containment_priority"),
        "future_checkpoints": [],
        "max_additional_gain_pct": None,
        "max_additional_giveback_pct": None,
        "price_at_hypothetical_protection": None,
        "later_recovery": None,
        "profit_preserved_estimate": None,
        "profit_missed_estimate": None,
        "time_to_new_high_minutes": None,
        "time_to_break_even_minutes": None,
        "opportunity_cost_estimate": None,
        "evidence_quality": "provisional",
        "data_provenance": "position_snapshot_and_loss_containment_decision",
    }


def evaluate_position_profit_protection_v1(
    position: Mapping[str, Any],
    *,
    ownership: Mapping[str, Any] | None = None,
    broker_position: Mapping[str, Any] | None = None,
    loss_containment_decision: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate a single position and produce a canonical profit-protection decision."""
    as_of = _iso(now)
    pos = dict(position or {})
    ownership_dict = dict(ownership or {})

    inputs = _resolve_position_inputs(pos, broker_position)
    blockers = _validate_inputs(inputs, policy, now)

    lane = inputs.get("lane")
    bands = _get_giveback_bands(lane, policy)
    metrics = _calculate_profit_metrics(inputs)
    thesis = _evaluate_thesis_state(pos)
    momentum = _evaluate_momentum_state(pos, metrics)
    continuation = _evaluate_continuation_confidence(pos, metrics, thesis, momentum)
    loss_containment = _evaluate_loss_containment_priority(loss_containment_decision)

    state, recommendation, reasons = _derive_state_and_recommendation(
        metrics, bands, thesis, momentum, continuation, loss_containment, blockers
    )

    confidence = 0.0 if blockers else 0.75
    if state == "THESIS_BROKEN":
        confidence = 0.85
    elif state == "EXIT_REVIEW":
        confidence = 0.80
    elif state == "PROTECT_PROFIT":
        confidence = 0.70
    elif state == "PROFIT_HEALTHY":
        confidence = 0.65

    ownership_state = ownership_dict.get("ownership") if ownership_dict else None
    if ownership_dict.get("legacy_quarantined"):
        ownership_classification = "LEGACY_QUARANTINED"
    elif ownership_dict.get("dust"):
        ownership_classification = "DUST_REVIEW"
    elif ownership_dict.get("broker_residue"):
        ownership_classification = "BROKER_RESIDUE_REVIEW"
    elif ownership_dict.get("unresolved"):
        ownership_classification = "UNRESOLVED_FAIL_CLOSED"
    elif ownership_state and ownership_state.startswith("ACTIVE"):
        ownership_classification = ownership_state
    else:
        ownership_classification = ownership_state or "UNKNOWN"

    decision = {
        "schema_version": "astra_profit_protection_position_decision_v1",
        "position_id": inputs.get("position_id"),
        "symbol": inputs.get("symbol"),
        "lane": lane or "UNAVAILABLE",
        "historical_lane": inputs.get("historical_lane") or "UNKNOWN",
        "management_policy": inputs.get("management_policy") or "NONE",
        "lane_derived_from_asset_class": bool(inputs.get("lane_derived_from_asset_class")),
        "horizon": inputs.get("horizon") or "UNAVAILABLE",
        "lane_recovery_status": inputs.get("lane_recovery_status") or "UNAVAILABLE",
        "horizon_recovery_status": inputs.get("horizon_recovery_status") or "UNAVAILABLE",
        "lane_source": inputs.get("lane_source") or "UNAVAILABLE",
        "horizon_source": inputs.get("horizon_source") or "UNAVAILABLE",
        "recovery_method": inputs.get("recovery_method") or "NONE",
        "ownership_classification": ownership_classification,
        "legacy_current_classification": ownership_classification,
        "entry_price": inputs.get("entry_price"),
        "current_price": inputs.get("current_price"),
        "current_return_pct": round(inputs.get("unrealized_pl_pct", 0.0), 6),
        "current_unrealized_pl_dollars": round(inputs.get("unrealized_pl_dollars", 0.0), 4),
        "peak_gain_pct": metrics.get("peak_gain_pct"),
        "peak_gain_dollars": inputs.get("peak_unrealized_dollars"),
        "giveback_pct_points": metrics.get("giveback_pct_points"),
        "giveback_ratio": metrics.get("giveback_ratio"),
        "capture_ratio": metrics.get("capture_ratio"),
        "retained_profit_pct": metrics.get("retained_profit_pct"),
        "retained_profit_dollars": metrics.get("retained_profit_dollars"),
        "giveback_bands": bands,
        "profit_state": state,
        "thesis_state": thesis.get("thesis_state"),
        "thesis_confidence": thesis.get("thesis_confidence"),
        "thesis_reason": thesis.get("thesis_reason"),
        "thesis_broken_signals": thesis.get("thesis_broken_signals"),
        "thesis_intact_signals": thesis.get("thesis_intact_signals"),
        "momentum_state": momentum.get("momentum_state"),
        "momentum_confidence": momentum.get("momentum_confidence"),
        "momentum_reason": momentum.get("momentum_reason"),
        "continuation_confidence": continuation.get("continuation_confidence"),
        "continuation_confidence_reasons": continuation.get("continuation_confidence_reasons"),
        "loss_containment": loss_containment,
        "canonical_recommendation": recommendation,
        "human_readable_reason": "; ".join(reasons),
        "confidence": round(confidence, 4),
        "data_completeness": "complete" if not blockers else "incomplete",
        "exact_blockers": list(blockers),
        "provider_native_timestamp": inputs.get("provider_native_timestamp"),
        "provider_native_timestamp_provenance": inputs.get("provider_native_timestamp_provenance"),
        "provider_native_timestamp_source": inputs.get("provider_native_timestamp_source"),
        "evidence_provenance": {
            "entry_price_source": "broker_position_avg_entry_price" if broker_position and _num(broker_position.get("avg_entry_price")) else "position_entry_price",
            "current_price_source": "broker_position_current_price" if broker_position and _num(broker_position.get("current_price")) else "position_current_price",
            "peak_gain_source": "canonical_peak_unrealized_gain" if metrics.get("peak_evidence_available") else "no_canonical_peak_evidence",
            "ownership_source": "provided_ownership" if ownership_dict else "not_provided",
            "loss_containment_source": "provided_loss_containment_decision" if loss_containment_decision else "not_provided",
            "lane_recovery_source": inputs.get("lane_source") or "UNAVAILABLE",
            "horizon_recovery_source": inputs.get("horizon_source") or "UNAVAILABLE",
            "provider_native_timestamp": inputs.get("provider_native_timestamp") or "UNAVAILABLE",
            "provider_native_timestamp_provenance": inputs.get("provider_native_timestamp_provenance") or "UNAVAILABLE",
            "provider_native_timestamp_source": inputs.get("provider_native_timestamp_source") or "UNAVAILABLE",
        },
        "advisory_only": True,
        "execution_authorized": False,
        "paper_action_ready": False,
        "broker_submission_allowed": False,
        "as_of": as_of,
    }

    decision_id = _decision_identity(
        inputs.get("position_id", ""),
        inputs.get("symbol", ""),
        lane,
        as_of,
        recommendation,
    )
    decision["decision_id"] = decision_id

    shadow = _build_shadow_record(
        inputs, metrics, state, recommendation, thesis, momentum, continuation, loss_containment, as_of
    )
    decision["shadow_record"] = shadow

    return decision


def run_profit_protection_review_v1(
    positions: Sequence[Mapping[str, Any]],
    *,
    ownership_map: Mapping[str, Mapping[str, Any]] | None = None,
    broker_positions: Mapping[str, Mapping[str, Any]] | None = None,
    loss_containment_decisions: Mapping[str, Mapping[str, Any]] | None = None,
    policy: Mapping[str, Any] | None = None,
    prior_state: Mapping[str, Any] | None = None,
    max_positions: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run a bounded advisory profit-protection review across positions.

    Consumes existing loss-containment decisions where available. Does not
    submit orders.
    """
    as_of = _iso(now)
    policy = dict(policy or {})
    policy.setdefault("lane_giveback_bands", LANE_GIVEBACK_BANDS)
    ownership_map = dict(ownership_map or {})
    broker_positions = dict(broker_positions or {})
    loss_containment_decisions = dict(loss_containment_decisions or {})
    prior_state = dict(prior_state or {})
    prior_decisions = dict(prior_state.get("decisions") or {})
    prior_events = dict(prior_state.get("events") or {})

    position_decisions: list[dict[str, Any]] = []
    lane_summaries: dict[str, dict[str, Any]] = {
        "DAY": {
            "positions_evaluated": 0, "profitable_positions": 0, "no_profit_history": 0,
            "healthy_profit": 0, "watch": 0, "giveback_elevated": 0,
            "protect_profit": 0, "exit_review": 0, "thesis_broken": 0,
            "loss_containment_priority": 0, "incomplete_data": 0,
        },
        "SWING": {
            "positions_evaluated": 0, "profitable_positions": 0, "no_profit_history": 0,
            "healthy_profit": 0, "watch": 0, "giveback_elevated": 0,
            "protect_profit": 0, "exit_review": 0, "thesis_broken": 0,
            "loss_containment_priority": 0, "incomplete_data": 0,
        },
        "CRYPTO": {
            "positions_evaluated": 0, "profitable_positions": 0, "no_profit_history": 0,
            "healthy_profit": 0, "watch": 0, "giveback_elevated": 0,
            "protect_profit": 0, "exit_review": 0, "thesis_broken": 0,
            "loss_containment_priority": 0, "incomplete_data": 0,
        },
    }
    new_decisions: dict[str, Any] = {}
    new_events: dict[str, Any] = {}
    blockers_by_position: dict[str, list[str]] = {}

    for row in positions:
        if not isinstance(row, dict):
            continue
        if len(position_decisions) >= max(1, int(max_positions)):
            break
        pid = _text(row.get("position_id") or row.get("asset_id") or row.get("symbol"))
        symbol = _text(row.get("symbol")).upper()
        ownership = dict(ownership_map.get(pid) or {})
        broker = dict(broker_positions.get(symbol) or {})
        lc_decision = dict(loss_containment_decisions.get(pid) or {})

        decision = evaluate_position_profit_protection_v1(
            row,
            ownership=ownership,
            broker_position=broker,
            loss_containment_decision=lc_decision,
            policy=policy,
            now=now,
        )
        position_decisions.append(decision)
        new_decisions[pid] = decision
        blockers_by_position[pid] = decision["exact_blockers"]

        lane = decision["lane"]
        if lane in lane_summaries:
            lane_summaries[lane]["positions_evaluated"] += 1
            if decision["profit_state"] == "NO_PROFIT_HISTORY":
                lane_summaries[lane]["no_profit_history"] += 1
            elif decision["profit_state"] == "PROFIT_HEALTHY":
                lane_summaries[lane]["healthy_profit"] += 1
            elif decision["profit_state"] == "PROFIT_WATCH":
                lane_summaries[lane]["watch"] += 1
            elif decision["profit_state"] == "GIVEBACK_ELEVATED":
                lane_summaries[lane]["giveback_elevated"] += 1
            elif decision["profit_state"] == "PROTECT_PROFIT":
                lane_summaries[lane]["protect_profit"] += 1
            elif decision["profit_state"] == "EXIT_REVIEW":
                lane_summaries[lane]["exit_review"] += 1
            elif decision["profit_state"] == "THESIS_BROKEN":
                lane_summaries[lane]["thesis_broken"] += 1
            elif decision["profit_state"] == "LOSS_CONTAINMENT_PRIORITY":
                lane_summaries[lane]["loss_containment_priority"] += 1
            elif decision["profit_state"] in ("DATA_INCOMPLETE_FAIL_CLOSED", "UNRESOLVED_FAIL_CLOSED"):
                lane_summaries[lane]["incomplete_data"] += 1

            if decision["current_return_pct"] > 0:
                lane_summaries[lane]["profitable_positions"] += 1

        # Emit durable events for material transitions.
        if decision["profit_state"] in {"PROTECT_PROFIT", "EXIT_REVIEW", "THESIS_BROKEN"}:
            event_type = decision["profit_state"]
            event_id = _event_identity(pid, symbol, lane, as_of, event_type)
            if event_id not in prior_events:
                new_events[event_id] = {
                    "event_id": event_id,
                    "event_type": event_type,
                    "position_id": pid,
                    "symbol": symbol,
                    "lane": lane,
                    "peak_gain_pct": decision["peak_gain_pct"],
                    "current_return_pct": decision["current_return_pct"],
                    "giveback_ratio": decision["giveback_ratio"],
                    "recommendation": decision["canonical_recommendation"],
                    "as_of": as_of,
                }

    total_evaluated = len(position_decisions)
    giveback_ratios = [d["giveback_ratio"] for d in position_decisions if d["giveback_ratio"] is not None]
    capture_ratios = [d["capture_ratio"] for d in position_decisions if d["capture_ratio"] is not None]

    metrics = {
        "positions_evaluated": total_evaluated,
        "profitable_positions": sum(s["profitable_positions"] for s in lane_summaries.values()),
        "no_profit_history": sum(s["no_profit_history"] for s in lane_summaries.values()),
        "healthy_profit_positions": sum(s["healthy_profit"] for s in lane_summaries.values()),
        "watch_recommendations": sum(s["watch"] for s in lane_summaries.values()),
        "giveback_elevated": sum(s["giveback_elevated"] for s in lane_summaries.values()),
        "protect_profit_recommendations": sum(s["protect_profit"] for s in lane_summaries.values()),
        "exit_review_recommendations": sum(s["exit_review"] for s in lane_summaries.values()),
        "thesis_broken_positions": sum(s["thesis_broken"] for s in lane_summaries.values()),
        "loss_containment_priority": sum(s["loss_containment_priority"] for s in lane_summaries.values()),
        "incomplete_data_fail_closed": sum(s["incomplete_data"] for s in lane_summaries.values()),
        "average_giveback_ratio": round(sum(giveback_ratios) / len(giveback_ratios), 6) if giveback_ratios else None,
        "median_giveback_ratio": round(sorted(giveback_ratios)[len(giveback_ratios) // 2], 6) if giveback_ratios else None,
        "average_capture_ratio": round(sum(capture_ratios) / len(capture_ratios), 6) if capture_ratios else None,
        "estimated_profit_preserved": None,
        "estimated_profit_missed": None,
        "continuation_after_recommendation": None,
        "recovery_to_new_high": None,
        "sample_size": total_evaluated,
        "policy_version": POLICY_SCHEMA_VERSION,
        "provisional_metrics": True,
    }

    merged_decisions = {**prior_decisions, **new_decisions}
    merged_events = {**prior_events, **new_events}
    if len(merged_decisions) > 500:
        merged_decisions = dict(list(merged_decisions.items())[-500:])
    if len(merged_events) > 500:
        merged_events = dict(list(merged_events.items())[-500:])

    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "policy_version": POLICY_SCHEMA_VERSION,
        "engine_version": ENGINE_SCHEMA_VERSION,
        "generated_timestamp": as_of,
        "advisory_only": True,
        "execution_authorized": False,
        "paper_action_ready": False,
        "broker_submission_allowed": False,
        "source_freshness": "position_snapshot_and_loss_containment_decision",
        "positions_evaluated": total_evaluated,
        "max_positions": max(1, int(max_positions)),
        "lane_summaries": lane_summaries,
        "position_decisions": position_decisions,
        "metrics": metrics,
        "exact_blockers": blockers_by_position,
        "provenance": {
            "policy_source": "astra_profit_protection_giveback_v1",
            "ownership_integration": "astra_legacy_quarantine_v1",
            "loss_containment_integration": "astra_loss_containment_engine_v1",
        },
        "retention": {
            "decision_retention_count": 500,
            "event_retention_count": 500,
            "bounded": True,
        },
        "health_status": "ok" if not any(blockers_by_position.values()) else "blocked_positions_present",
        "state": {
            "schema_version": "astra_profit_protection_state_v1",
            "decisions": merged_decisions,
            "events": merged_events,
            "as_of": as_of,
        },
    }
