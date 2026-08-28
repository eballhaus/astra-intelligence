"""Lane-specific loss containment, bounce-back preservation, and hard drawdown protection.

This module is strictly advisory/shadow-only. It produces canonical position-level
recommendations and durable advisory records but never places, submits, modifies,
cancels, or authorizes broker orders. It integrates with the existing canonical
position ownership model in `astra_legacy_quarantine_v1` and does not duplicate it.

Policy version: astra_loss_containment_policy_v1
Engine version: astra_loss_containment_engine_v1
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

from engine.astra_canonical_market_timestamp_v1 import canonical_market_timestamp_v1


# Policy constants — versioned, central, conservative candidates.
POLICY_SCHEMA_VERSION = "astra_loss_containment_policy_v1"
ENGINE_SCHEMA_VERSION = "astra_loss_containment_engine_v1"
OUTPUT_SCHEMA_VERSION = "astra_loss_containment_decision_envelope_v1"


# Lane-specific loss containment thresholds as paper-policy candidates.
# These are initial safety boundaries, not proven optimal parameters.
LANE_LOSS_THRESHOLDS: dict[str, dict[str, float]] = {
    "DAY": {
        "early_review_pct": -2.0,
        "mandatory_review_pct": -3.0,
        "hard_boundary_pct": -4.0,
    },
    "CRYPTO": {
        "early_review_pct": -3.5,
        "mandatory_review_pct": -5.0,
        "hard_boundary_pct": -6.0,
    },
    "SWING": {
        "early_review_pct": -4.5,
        "mandatory_review_pct": -6.0,
        "hard_boundary_pct": -8.0,
    },
}

# Conservative profit-protection candidate: flag giveback beyond 50% of peak gain.
PROFIT_GIVEBACK_THRESHOLD_PCT = 0.50

# Bounded recovery window defaults by lane (candidate values).
LANE_RECOVERY_WINDOW_MINUTES: dict[str, float] = {
    "DAY": 60.0,
    "CRYPTO": 240.0,
    "SWING": 2880.0,
}

# Staleness tolerance for critical price evidence (minutes).
# The latest_price_by_symbol timestamp is set to the cycle snapshot time
# (_now_iso()) at the moment broker data is fetched, so it is always fresh.
# This tolerance catches the edge case where the timestamp resolution falls
# through to a stale position DB timestamp.
DEFAULT_PRICE_STALENESS_MINUTES = 30.0

# Canonical loss-containment states.
LOSS_CONTAINMENT_STATES = frozenset({
    "HEALTHY",
    "EARLY_REVIEW",
    "MANDATORY_REVIEW",
    "BOUNDED_RECOVERY",
    "HARD_BOUNDARY_BREACH",
    "THESIS_BROKEN",
    "PROTECT_PROFIT",
    "DATA_INCOMPLETE_FAIL_CLOSED",
    "UNRESOLVED_FAIL_CLOSED",
})

# Canonical advisory recommendations.
CANONICAL_RECOMMENDATIONS = frozenset({
    "HOLD",
    "WATCH",
    "BOUNDED_RECOVERY",
    "PROTECT_PROFIT",
    "EXIT_REVIEW",
    "REPLACE_CANDIDATE",
    "THESIS_BROKEN",
    "HARD_LOSS_EXIT_REQUIRED_ADVISORY",
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
    """Deterministic decision identifier for deduplication.

    The identity intentionally excludes the observed loss percentage so that a
    stable advisory state is not rewritten every tick. A change in
    recommendation or severity produces a new event.
    """
    symbol = _text(symbol).upper()
    lane = _lane(lane)
    seed = f"{position_id}|{symbol}|{lane}|{recommendation}|{as_of[:19]}"
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _event_identity(position_id: str, symbol: str, lane: str, as_of: str, event_type: str) -> str:
    """Deterministic breach/transition event identity.

    Uses truncated timestamp to avoid duplicate breach records every cycle.
    """
    symbol = _text(symbol).upper()
    lane = _lane(lane)
    seed = f"event|{position_id}|{symbol}|{lane}|{event_type}|{as_of[:19]}"
    import hashlib
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:24]


def _atomic_write_json(path: str, payload: dict[str, Any]) -> None:
    """Write JSON atomically using a temporary file and os.replace."""
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


def load_loss_containment_state_v1(path: str) -> dict[str, Any]:
    """Load prior advisory state; malformed files are preserved as forensic."""
    raw = _load_json(path)
    if not raw:
        return {
            "schema_version": "astra_loss_containment_state_v1",
            "loaded": False,
            "forensic": None,
            "decisions": {},
            "events": {},
            "as_of": _iso(),
        }
    if not isinstance(raw, dict):
        return {
            "schema_version": "astra_loss_containment_state_v1",
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
        "schema_version": "astra_loss_containment_state_v1",
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


def save_loss_containment_state_v1(path: str, state: Mapping[str, Any]) -> None:
    """Persist advisory state atomically."""
    payload = {
        "schema_version": "astra_loss_containment_state_v1",
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
    latest_price: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve canonical inputs for loss containment from approved sources.

    Priority: broker_position > position > latest_price. Missing critical facts
    are reported as blockers rather than inferred.
    """
    pos = dict(position or {})
    broker = dict(broker_position or {})
    latest = dict(latest_price or {})

    symbol = _text(
        pos.get("symbol")
        or broker.get("symbol")
        or latest.get("symbol")
    ).upper()
    position_id = _text(
        pos.get("position_id")
        or pos.get("asset_id")
        or broker.get("id")
        or broker.get("asset_id")
        or symbol
    )

    # A recovery-aware caller has already arbitrated lane ownership.  Never
    # re-derive it from asset class or horizon, because that would turn an
    # unavailable entry record into an invented lane threshold.
    #
    # When recovery returns UNAVAILABLE and no broker lane exists, the engine
    # derives an *effective_lane* from asset_class for threshold rails only.
    # The *historical_lane* remains UNKNOWN — management policy is not ownership.
    recovery_present = "lane_recovery_status" in pos
    lane_recovery_unavailable = recovery_present and _text(pos.get("lane_recovery_status")).upper() == "UNAVAILABLE"
    lane = _lane(pos.get("lane_id"))
    explicit_lane = _text(pos.get("lane_id")).upper()
    historical_lane = lane if lane else "UNKNOWN"
    derived_lane = False
    management_policy = "NONE"

    if not lane and explicit_lane:
        # Normalize cohort labels (SCALP) to their canonical risk-policy lane (DAY).
        if explicit_lane == "SCALP":
            lane = "DAY"
        else:
            lane = explicit_lane
        historical_lane = lane
    if not lane and (not recovery_present or lane_recovery_unavailable):
        asset_class = _text(
            pos.get("asset_class")
            or pos.get("asset_type")
            or broker.get("asset_class")
            or broker.get("asset_type")
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

    # When lane was proven (not derived from asset_class), historical_lane == lane.
    if lane and not derived_lane and historical_lane == "UNKNOWN":
        historical_lane = lane

    # Quantity: broker first, then position.
    quantity = abs(
        _num(broker.get("qty"))
        or _num(broker.get("qty_available"))
        or _num(pos.get("qty"))
        or _num(pos.get("quantity"))
        or 0.0
    )

    # Entry price: prefer broker-confirmed avg entry, then explicit position field.
    entry_price = (
        _num(broker.get("avg_entry_price"))
        or _num(pos.get("avg_entry_price"))
        or _num(pos.get("entry_price"))
        or _num(pos.get("cost_basis"))
        or 0.0
    )

    # Current price: broker current price, then latest price snapshot, then position mark.
    current_price = (
        _num(broker.get("current_price"))
        or _num(broker.get("market_price"))
        or _num(broker.get("lastday_price"))
        or _num(latest.get("price"))
        or _num(latest.get("current_price"))
        or _num(latest.get("last_price"))
        or _num(pos.get("current_price"))
        or _num(pos.get("last_price"))
        or _num(pos.get("market_price"))
        or 0.0
    )

    market_value = (
        _num(broker.get("market_value"))
        or _num(pos.get("market_value"))
        or (quantity * current_price if quantity > 0 and current_price > 0 else 0.0)
    )

    cost_basis = (
        _num(pos.get("cost_basis"))
        or (entry_price * quantity if entry_price > 0 and quantity > 0 else 0.0)
    )

    # Canonical percent fields are percentage points (for example -16.667),
    # while Alpaca's ``unrealized_plpc`` is a fraction (for example -0.16667).
    # Never let a legacy fraction outrank a canonical percentage, and convert
    # that fraction exactly once at this producer/consumer boundary.
    unrealized_pl_pct = None
    for value in (
        pos.get("unrealized_pl_pct"),
        pos.get("unrealized_return_pct"),
        pos.get("unrealized_pct"),
    ):
        parsed = _num(value)
        if parsed is not None:
            unrealized_pl_pct = parsed
            break
    if unrealized_pl_pct is None:
        for value in (broker.get("unrealized_plpc"), pos.get("unrealized_plpc")):
            parsed = _num(value)
            if parsed is not None:
                # Historical fixtures stored percentage points under the raw
                # Alpaca name. Real Alpaca fractions are bounded to [-1, 1],
                # so retain that legacy compatibility without double-scaling
                # an already-normalized value.
                unrealized_pl_pct = parsed * 100.0 if abs(parsed) <= 1.0 else parsed
                break
    if unrealized_pl_pct is None and cost_basis > 0 and market_value > 0:
        unrealized_pl_pct = ((market_value - cost_basis) / cost_basis) * 100.0
    if unrealized_pl_pct is None:
        unrealized_pl_pct = 0.0

    unrealized_pl_dollars = (
        _num(pos.get("unrealized_pl"))
        or _num(pos.get("unrealized_pnl"))
        or (market_value - cost_basis if market_value > 0 and cost_basis > 0 else 0.0)
    )

    # Retrieval timestamps document cycle/fetch time only.  The canonical
    # contract decides whether a provider-native market observation exists.
    retrieval_timestamp = _text(latest.get("retrieval_timestamp") or latest.get("retrieved_at") or latest.get("fetched_at"))
    provider_native_ts = canonical_market_timestamp_v1(
        {
            **pos,
            **broker,
            **latest,
            "observation_timestamp": broker.get("observation_timestamp")
            or latest.get("observation_timestamp")
            or pos.get("observation_timestamp"),
            "market_timestamp": broker.get("market_timestamp")
            or latest.get("market_timestamp")
            or pos.get("market_timestamp"),
            "quote_timestamp": broker.get("quote_timestamp") or latest.get("quote_timestamp") or pos.get("quote_timestamp"),
            "trade_timestamp": broker.get("trade_timestamp") or latest.get("trade_timestamp") or pos.get("trade_timestamp"),
            "retrieval_timestamp": retrieval_timestamp,
        },
        source_type="QUOTE" if (
            broker.get("quote_timestamp")
            or latest.get("quote_timestamp")
            or pos.get("quote_timestamp")
            or broker.get("provider_native_timestamp")
            or latest.get("provider_native_timestamp")
            or pos.get("provider_native_timestamp")
        ) else None,
    )
    provider_native_timestamp = provider_native_ts["provider_native_timestamp"]
    provider_native_timestamp_provenance = provider_native_ts["provenance"]
    provider_native_timestamp_source = provider_native_ts["source_field"]
    market_observation_timestamp = provider_native_ts["market_observation_timestamp"]
    price_timestamp = market_observation_timestamp

    holding_minutes = _age_minutes(
        pos.get("entry_timestamp")
        or pos.get("entry_filled_at")
        or pos.get("created_at")
    )

    peak_unrealized_pct = _num(
        pos.get("peak_unrealized_gain_pct")
        or pos.get("max_favorable_excursion_pct")
        or pos.get("mfe_pct")
    )
    max_adverse_pct = _num(
        pos.get("max_adverse_excursion_pct")
        or pos.get("mae_pct")
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
        "price_timestamp": price_timestamp,
        "market_observation_timestamp": market_observation_timestamp,
        "retrieval_timestamp": retrieval_timestamp,
        "provider_native_timestamp": provider_native_timestamp,
        "provider_native_timestamp_provenance": provider_native_timestamp_provenance,
        "provider_native_timestamp_source": provider_native_timestamp_source,
        "market_observation_unavailable": bool(provider_native_ts["market_observation_unavailable"]),
        "market_timestamp_contract": provider_native_ts,
        "holding_minutes": holding_minutes,
        "peak_unrealized_pct": peak_unrealized_pct,
        "max_adverse_pct": max_adverse_pct,
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
    """Return critical blockers; empty list means inputs are sufficient to evaluate."""
    blockers: list[str] = []
    if not inputs.get("position_id"):
        blockers.append("MISSING_POSITION_ID")
    if not inputs.get("symbol"):
        blockers.append("MISSING_SYMBOL")

    lane = inputs.get("lane")
    recovery_present = bool(inputs.get("lane_recovery_status"))
    if lane:
        if lane not in LANE_LOSS_THRESHOLDS:
            blockers.append(f"UNKNOWN_LANE:{lane}")
    elif recovery_present:
        blockers.extend(str(item) for item in inputs.get("recovery_exact_blockers") or [] if str(item))
    else:
        blockers.append("MISSING_LANE")
    if recovery_present and inputs.get("horizon_recovery_status") != "RESOLVED":
        # Horizon recovery unavailable is advisory; the engine can still evaluate
        # threshold state against lane rails.  Exit eligibility uses horizon
        # separately and will downgrade its recommendation accordingly.
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
        # When market observation timestamp is missing, the price cannot be
        # proven fresh.  Retrieval time alone is insufficient.
        blockers.append("MARKET_OBSERVATION_TIMESTAMP_UNAVAILABLE")
    elif price_ts:
        age = _age_minutes(price_ts, now)
        if age is None:
            blockers.append("PRICE_TIMESTAMP_UNPARSEABLE")
        else:
            staleness = float(
                (policy or {}).get("price_staleness_minutes", DEFAULT_PRICE_STALENESS_MINUTES)
            )
            if age > staleness:
                blockers.append(f"PRICE_STALE:{round(age, 2)}min_exceeds_{staleness}min")
    else:
        blockers.append("MISSING_PRICE_TIMESTAMP")

    return blockers


def _get_thresholds(
    lane: str,
    policy_override: Mapping[str, Any] | None = None,
) -> dict[str, float]:
    """Return the lane thresholds with optional policy override."""
    override = dict(policy_override or {}).get("lane_thresholds", {})
    defaults = dict(LANE_LOSS_THRESHOLDS.get(lane, {}))
    lane_override = dict(override.get(lane, {}))
    return {
        "early_review_pct": float(lane_override.get("early_review_pct", defaults.get("early_review_pct", -999.0))),
        "mandatory_review_pct": float(lane_override.get("mandatory_review_pct", defaults.get("mandatory_review_pct", -999.0))),
        "hard_boundary_pct": float(lane_override.get("hard_boundary_pct", defaults.get("hard_boundary_pct", -999.0))),
    }


def _threshold_state(
    unrealized_pct: float,
    thresholds: dict[str, float],
) -> str:
    """Return loss-threshold state based on current return percentage."""
    if unrealized_pct >= 0.0:
        return "HEALTHY"
    if unrealized_pct <= thresholds["hard_boundary_pct"]:
        return "HARD_BOUNDARY_BREACH"
    if unrealized_pct <= thresholds["mandatory_review_pct"]:
        return "MANDATORY_REVIEW"
    if unrealized_pct <= thresholds["early_review_pct"]:
        return "EARLY_REVIEW"
    return "HEALTHY"


def _evaluate_thesis_state(
    position: Mapping[str, Any],
    inputs: dict[str, Any],
    threshold_state: str,
) -> dict[str, Any]:
    """Evaluate thesis health from available evidence.

    Returns a dict with thesis_state, confidence, and reasons. This is a
    bounded heuristic that fails closed when evidence is missing.
    """
    pos = dict(position or {})
    invalidation = _as_string_list(pos.get("thesis_invalidation_conditions"))
    support = _as_string_list(pos.get("thesis_supporting_conditions"))
    catalyst = _text(pos.get("catalyst_state") or pos.get("catalyst_context_label"))
    thesis_summary = _text(pos.get("thesis") or pos.get("intelligence_summary"))

    broken_signals: list[str] = []
    intact_signals: list[str] = []

    if invalidation:
        intact_signals.append("invalidation_conditions_defined")
    if support:
        intact_signals.append("support_conditions_defined")
    if catalyst:
        intact_signals.append("catalyst_state_present")
    if thesis_summary:
        intact_signals.append("thesis_summary_present")

    # Explicit thesis-broken flag from upstream is authoritative.
    explicit_broken = bool(
        pos.get("thesis_broken")
        or pos.get("thesis_invalidated")
        or pos.get("setup_failed")
    )
    if explicit_broken:
        broken_signals.append("explicit_thesis_broken_flag")

    # Support failure heuristic.
    support_failed = bool(
        pos.get("support_failed")
        or pos.get("support_broken")
        or pos.get("key_support_violated")
    )
    if support_failed:
        broken_signals.append("support_failure_flag")

    # Catalyst invalidation heuristic.
    catalyst_invalid = bool(
        pos.get("catalyst_invalidated")
        or pos.get("catalyst_expired")
        or pos.get("catalyst_failed")
    )
    if catalyst_invalid:
        broken_signals.append("catalyst_invalidated_flag")

    if broken_signals:
        return {
            "thesis_state": "THESIS_BROKEN",
            "thesis_confidence": 0.85,
            "thesis_reason": "explicit_or_heuristic_thesis_failure",
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


def _evaluate_momentum_state(
    position: Mapping[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate momentum from available evidence.

    Returns a dict with momentum_state, confidence, and reasons.
    """
    pos = dict(position or {})
    momentum_label = _text(pos.get("momentum_state") or pos.get("trend_state")).upper()
    improving_signals: list[str] = []
    deteriorating_signals: list[str] = []

    if momentum_label in {"IMPROVING", "BULLISH", "STRENGTHENING", "RECOVERING"}:
        improving_signals.append("momentum_label_improving")
    elif momentum_label in {"DETERIORATING", "BEARISH", "WEAKENING", "FADING"}:
        deteriorating_signals.append("momentum_label_deteriorating")
    elif momentum_label:
        improving_signals.append("momentum_label_present")

    # Simple excursion-based momentum: if MAE is beyond current loss, the
    # position has already seen worse and recovered somewhat.
    mae = inputs.get("max_adverse_pct")
    current_loss = inputs.get("unrealized_pl_pct", 0.0)
    if mae is not None and mae < 0 and current_loss > mae * 0.95:
        improving_signals.append("current_loss_better_than_max_adverse_excursion")

    if deteriorating_signals:
        return {
            "momentum_state": "DETERIORATING",
            "momentum_confidence": 0.65,
            "momentum_reason": "momentum_signals_deteriorating",
            "improving_signals": improving_signals,
            "deteriorating_signals": deteriorating_signals,
        }
    if improving_signals:
        return {
            "momentum_state": "IMPROVING",
            "momentum_confidence": 0.6,
            "momentum_reason": "momentum_signals_improving",
            "improving_signals": improving_signals,
            "deteriorating_signals": deteriorating_signals,
        }
    return {
        "momentum_state": "UNKNOWN",
        "momentum_confidence": 0.5,
        "momentum_reason": "no_momentum_evidence",
        "improving_signals": [],
        "deteriorating_signals": [],
    }


def _as_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []


def _evaluate_recovery_eligibility(
    position: Mapping[str, Any],
    inputs: dict[str, Any],
    threshold_state: str,
    thesis: Mapping[str, Any],
    momentum: Mapping[str, Any],
    blockers: Sequence[str],
    policy: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    prior_recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Determine whether a position may receive BOUNDED_RECOVERY.

    Recovery requires:
      1. Not a hard-boundary breach.
      2. Thesis not broken.
      3. Critical evidence sufficiently complete.
      4. Time-bounded window.
      5. Explicit expiration conditions.
    """
    ineligible_reasons: list[str] = []
    eligibility_reasons: list[str] = []

    if threshold_state == "HARD_BOUNDARY_BREACH":
        ineligible_reasons.append("hard_boundary_breached")
    if threshold_state == "HEALTHY":
        ineligible_reasons.append("position_not_in_review")
    if thesis.get("thesis_state") == "THESIS_BROKEN":
        ineligible_reasons.append("thesis_broken")
    if thesis.get("thesis_state") == "THESIS_UNKNOWN":
        ineligible_reasons.append("thesis_evidence_unknown")
    if momentum.get("momentum_state") == "DETERIORATING":
        ineligible_reasons.append("momentum_deteriorating")
    if blockers:
        ineligible_reasons.append("critical_evidence_incomplete")

    # Holding-period compatibility with intended horizon.
    lane = inputs.get("lane")
    holding_minutes = inputs.get("holding_minutes")
    expected_window = LANE_RECOVERY_WINDOW_MINUTES.get(lane, 60.0)
    if holding_minutes is not None and holding_minutes > expected_window * 3:
        ineligible_reasons.append("holding_period_exceeds_expected_horizon")

    # Support/catalyst intact.
    pos = dict(position or {})
    if bool(pos.get("support_failed") or pos.get("support_broken")):
        ineligible_reasons.append("support_failed")
    if bool(pos.get("catalyst_invalidated") or pos.get("catalyst_expired")):
        ineligible_reasons.append("catalyst_invalidated")

    # Opportunity cost / replacement candidate.
    replacement_better = bool(pos.get("replacement_candidate_better") or pos.get("superior_replacement_available"))
    if replacement_better:
        ineligible_reasons.append("superior_replacement_candidate_available")

    if not ineligible_reasons:
        eligibility_reasons.append("thesis_intact_and_loss_within_hard_boundary")
        eligibility_reasons.append("momentum_not_deteriorating")
        eligibility_reasons.append("critical_evidence_complete")
        eligibility_reasons.append("expected_horizon_compatible")

    recovery_window_minutes = float(
        (policy or {}).get("recovery_window_minutes", {}).get(lane, expected_window)
        if isinstance((policy or {}).get("recovery_window_minutes"), dict)
        else LANE_RECOVERY_WINDOW_MINUTES.get(lane, expected_window)
    )
    if prior_recovery:
        started = prior_recovery.get("recovery_started_at")
        if started:
            age = _age_minutes(started, now)
            if age is not None and age > recovery_window_minutes:
                ineligible_reasons.append("recovery_window_expired")

    eligible = not ineligible_reasons
    started_at = _iso(now)
    if prior_recovery and prior_recovery.get("recovery_started_at"):
        started_at = prior_recovery["recovery_started_at"]

    expires_at = (
        (now or datetime.now(timezone.utc)) + timedelta(minutes=recovery_window_minutes)
    ).isoformat().replace("+00:00", "Z")

    return {
        "recovery_eligible": eligible,
        "recovery_window_minutes": recovery_window_minutes,
        "recovery_started_at": started_at,
        "recovery_expires_at": expires_at,
        "recovery_eligibility_reasons": eligibility_reasons,
        "recovery_ineligible_reasons": ineligible_reasons,
        "recovery_cancellation_triggers": [
            "hard_boundary_breach",
            "thesis_failure",
            "support_failure",
            "continued_momentum_deterioration",
            "catalyst_invalidation",
            "recovery_window_expiration",
            "superior_replacement_opportunity",
            "worsening_opportunity_cost",
            "stale_or_missing_critical_evidence",
        ],
    }


def _evaluate_profit_protection(
    position: Mapping[str, Any],
    inputs: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate profit giveback and return a protect-profit signal.

    Returns a dict with protect_profit, peak, current, giveback, and reason.
    Missing peak evidence is reported, not fabricated.
    """
    peak_pct = inputs.get("peak_unrealized_pct")
    current_pct = inputs.get("unrealized_pl_pct", 0.0)
    if peak_pct is None:
        return {
            "protect_profit": False,
            "profit_protection_available": False,
            "peak_unrealized_pct": None,
            "current_unrealized_pct": current_pct,
            "profit_giveback_pct": None,
            "capture_ratio": None,
            "profit_protection_reason": "peak_unrealized_gain_evidence_missing",
        }
    giveback = peak_pct - current_pct
    capture_ratio = (current_pct / peak_pct) if peak_pct > 0 else None
    if current_pct < 0:
        # Already in loss, profit protection is moot.
        return {
            "protect_profit": False,
            "profit_protection_available": True,
            "peak_unrealized_pct": peak_pct,
            "current_unrealized_pct": current_pct,
            "profit_giveback_pct": giveback,
            "capture_ratio": capture_ratio,
            "profit_protection_reason": "current_loss_not_profit_protection_candidate",
        }
    if giveback >= peak_pct * PROFIT_GIVEBACK_THRESHOLD_PCT and peak_pct > 0:
        return {
            "protect_profit": True,
            "profit_protection_available": True,
            "peak_unrealized_pct": peak_pct,
            "current_unrealized_pct": current_pct,
            "profit_giveback_pct": giveback,
            "capture_ratio": capture_ratio,
            "profit_protection_reason": "giveback_exceeded_threshold_of_peak_gain",
        }
    return {
        "protect_profit": False,
        "profit_protection_available": True,
        "peak_unrealized_pct": peak_pct,
        "current_unrealized_pct": current_pct,
        "profit_giveback_pct": giveback,
        "capture_ratio": capture_ratio,
        "profit_protection_reason": "giveback_within_tolerance",
    }


def _canonical_recommendation(
    threshold_state: str,
    thesis: Mapping[str, Any],
    recovery: Mapping[str, Any],
    profit_protection: Mapping[str, Any],
    blockers: Sequence[str],
    preexisting_breach: bool,
) -> str:
    """Return the single canonical advisory recommendation."""
    if blockers:
        return "DATA_INCOMPLETE_FAIL_CLOSED"
    if threshold_state == "HARD_BOUNDARY_BREACH":
        return "HARD_LOSS_EXIT_REQUIRED_ADVISORY"
    if thesis.get("thesis_state") == "THESIS_BROKEN":
        return "THESIS_BROKEN"
    if profit_protection.get("protect_profit"):
        return "PROTECT_PROFIT"
    if recovery.get("recovery_eligible"):
        return "BOUNDED_RECOVERY"
    if threshold_state == "MANDATORY_REVIEW":
        return "EXIT_REVIEW"
    if threshold_state == "EARLY_REVIEW":
        return "WATCH"
    return "HOLD"


def _hard_boundary_status(
    threshold_state: str,
    inputs: dict[str, Any],
    thresholds: dict[str, float],
    ownership: Mapping[str, Any] | None,
    prior_events: Mapping[str, Any] | None,
    as_of: str,
) -> dict[str, Any]:
    """Produce hard-boundary status, distinguishing preexisting vs new breaches.

    A breach is preexisting if a prior breach event exists for this position or
    if the position was already beyond the boundary before this upgrade.
    """
    prior = dict(prior_events or {})
    had_prior_breach = bool(
        prior.get("HARD_BOUNDARY_BREACH")
        or prior.get("PREEXISTING_HARD_BOUNDARY_BREACH")
        or prior.get("hard_boundary_breach")
    )
    ownership_dict = dict(ownership or {})
    preexisting_marker = bool(
        ownership_dict.get("legacy_quarantined")
        or ownership_dict.get("preexisting_hard_boundary_breach")
        or inputs.get("preexisting_hard_boundary_breach")
        or had_prior_breach
    )

    if threshold_state != "HARD_BOUNDARY_BREACH":
        return {
            "hard_boundary_breached": False,
            "preexisting_breach": preexisting_marker,
            "new_breach": False,
            "hard_boundary_pct": thresholds["hard_boundary_pct"],
            "observed_loss_pct": inputs.get("unrealized_pl_pct", 0.0),
        }

    if preexisting_marker:
        return {
            "hard_boundary_breached": True,
            "preexisting_breach": True,
            "new_breach": False,
            "hard_boundary_pct": thresholds["hard_boundary_pct"],
            "observed_loss_pct": inputs.get("unrealized_pl_pct", 0.0),
        }

    return {
        "hard_boundary_breached": True,
        "preexisting_breach": False,
        "new_breach": True,
        "hard_boundary_pct": thresholds["hard_boundary_pct"],
        "observed_loss_pct": inputs.get("unrealized_pl_pct", 0.0),
    }


def _build_shadow_record(
    position: Mapping[str, Any],
    inputs: dict[str, Any],
    recommendation: str,
    threshold_state: str,
    thesis: Mapping[str, Any],
    momentum: Mapping[str, Any],
    recovery: Mapping[str, Any],
    hard_boundary: Mapping[str, Any],
    profit_protection: Mapping[str, Any],
    as_of: str,
) -> dict[str, Any]:
    """Build bounded shadow evidence for later counterfactual evaluation."""
    return {
        "position_id": inputs.get("position_id"),
        "symbol": inputs.get("symbol"),
        "lane": inputs.get("lane"),
        "decision_timestamp": as_of,
        "entry_price": inputs.get("entry_price"),
        "decision_price": inputs.get("current_price"),
        "loss_pct_at_decision": inputs.get("unrealized_pl_pct"),
        "unrealized_pl_dollars": inputs.get("unrealized_pl_dollars"),
        "policy_thresholds": {
            "early_review_pct": None,
            "mandatory_review_pct": None,
            "hard_boundary_pct": None,
        },
        "advisory_recommendation": recommendation,
        "threshold_state": threshold_state,
        "thesis_state": thesis.get("thesis_state"),
        "momentum_state": momentum.get("momentum_state"),
        "recovery_eligible": recovery.get("recovery_eligible"),
        "hard_boundary_status": {
            "breached": hard_boundary.get("hard_boundary_breached"),
            "preexisting": hard_boundary.get("preexisting_breach"),
            "new": hard_boundary.get("new_breach"),
        },
        "profit_protection": {
            "protect_profit": profit_protection.get("protect_profit"),
            "peak_unrealized_pct": profit_protection.get("peak_unrealized_pct"),
            "profit_giveback_pct": profit_protection.get("profit_giveback_pct"),
        },
        # Future checkpoints are placeholders; they are populated later by the
        # bounded shadow update path without broker API calls.
        "future_checkpoints": [],
        "max_additional_loss_pct": None,
        "max_rebound_pct": None,
        "returned_above_break_even": None,
        "recovered_above_decision_price": None,
        "avoided_loss_estimate": None,
        "missed_rebound_estimate": None,
        "estimated_profit_saved": None,
        "opportunity_cost_estimate": None,
        "time_to_recovery_or_deterioration_minutes": None,
        "evidence_quality": "provisional",
        "data_provenance": "position_snapshot_and_broker_position",
    }


def evaluate_position_loss_containment_v1(
    position: Mapping[str, Any],
    *,
    ownership: Mapping[str, Any] | None = None,
    broker_position: Mapping[str, Any] | None = None,
    latest_price: Mapping[str, Any] | None = None,
    policy: Mapping[str, Any] | None = None,
    prior_state: Mapping[str, Any] | None = None,
    prior_recovery: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate a single position and produce a canonical loss-containment decision.

    The result is advisory only. It includes all required safety flags and never
    authorizes execution.
    """
    as_of = _iso(now)
    pos = dict(position or {})
    ownership_dict = dict(ownership or {})
    prior = dict(prior_state or {})
    prior_events = dict(prior.get("events") or {})
    prior_decision = dict(prior.get("decisions") or {})
    prior_recovery_for_pid = prior_recovery or dict(prior_decision.get("recovery") or {})

    inputs = _resolve_position_inputs(pos, broker_position, latest_price)
    blockers = _validate_inputs(inputs, policy, now)

    lane = inputs.get("lane")
    thresholds = _get_thresholds(lane, policy)
    threshold_state = "DATA_INCOMPLETE_FAIL_CLOSED" if blockers else _threshold_state(
        inputs.get("unrealized_pl_pct", 0.0), thresholds
    )

    thesis = _evaluate_thesis_state(pos, inputs, threshold_state)
    momentum = _evaluate_momentum_state(pos, inputs)
    profit_protection = _evaluate_profit_protection(pos, inputs)
    recovery = _evaluate_recovery_eligibility(
        pos,
        inputs,
        threshold_state,
        thesis,
        momentum,
        blockers,
        policy,
        now,
        prior_recovery_for_pid,
    )
    hard_boundary = _hard_boundary_status(
        threshold_state,
        inputs,
        thresholds,
        ownership_dict,
        prior_events,
        as_of,
    )

    recommendation = _canonical_recommendation(
        threshold_state,
        thesis,
        recovery,
        profit_protection,
        blockers,
        hard_boundary.get("preexisting_breach", False),
    )

    # Distinguish state contract from recommendation.
    state = threshold_state
    if state == "DATA_INCOMPLETE_FAIL_CLOSED" and not blockers:
        state = "UNRESOLVED_FAIL_CLOSED"
    if state in ("HEALTHY", "EARLY_REVIEW", "MANDATORY_REVIEW"):
        if recommendation == "PROTECT_PROFIT":
            state = "PROTECT_PROFIT"
        elif recommendation == "BOUNDED_RECOVERY":
            state = "BOUNDED_RECOVERY"
        elif recommendation == "THESIS_BROKEN":
            state = "THESIS_BROKEN"

    reason_parts: list[str] = []
    if blockers:
        reason_parts.append("blocked:" + ";".join(blockers))
    else:
        reason_parts.append(f"threshold_state={state}")
        reason_parts.append(f"thesis_state={thesis.get('thesis_state')}")
        reason_parts.append(f"momentum_state={momentum.get('momentum_state')}")
        if recommendation == "HARD_LOSS_EXIT_REQUIRED_ADVISORY":
            reason_parts.append(
                f"observed_loss={inputs.get('unrealized_pl_pct', 0.0):.4f}% "
                f"exceeds_hard_boundary={thresholds['hard_boundary_pct']:.2f}%"
            )
        elif recommendation == "BOUNDED_RECOVERY":
            reason_parts.append(f"recovery_window_minutes={recovery.get('recovery_window_minutes')}")
        elif recommendation == "PROTECT_PROFIT":
            reason_parts.append(
                f"peak={profit_protection.get('peak_unrealized_pct'):.4f}% "
                f"giveback={profit_protection.get('profit_giveback_pct'):.4f}%"
            )

    confidence = 0.0 if blockers else 0.75
    if blockers:
        confidence = 0.0
    elif thesis.get("thesis_state") == "THESIS_BROKEN":
        confidence = 0.85
    elif recommendation == "HARD_LOSS_EXIT_REQUIRED_ADVISORY":
        confidence = 0.95
    elif recommendation == "PROTECT_PROFIT":
        confidence = 0.7
    elif recommendation == "BOUNDED_RECOVERY":
        confidence = 0.55

    ownership_state = ownership_dict.get("ownership") if ownership_dict else None
    legacy_current = ownership_state if ownership_state and ownership_state.startswith("ACTIVE") else None
    if ownership_dict.get("legacy_quarantined"):
        legacy_current = "LEGACY_QUARANTINED"
    elif ownership_dict.get("dust"):
        legacy_current = "DUST_REVIEW"
    elif ownership_dict.get("broker_residue"):
        legacy_current = "BROKER_RESIDUE_REVIEW"
    elif ownership_dict.get("unresolved"):
        legacy_current = "UNRESOLVED_FAIL_CLOSED"
    elif not ownership_dict:
        legacy_current = "UNKNOWN"

    decision = {
        "schema_version": "astra_loss_containment_position_decision_v1",
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
        "ownership_classification": legacy_current or "UNKNOWN",
        "legacy_current_classification": legacy_current or "UNKNOWN",
        "current_return_pct": round(inputs.get("unrealized_pl_pct", 0.0), 6),
        "current_unrealized_pl_dollars": round(inputs.get("unrealized_pl_dollars", 0.0), 4),
        "thresholds": thresholds,
        "threshold_state": state,
        "thesis_state": thesis.get("thesis_state"),
        "thesis_confidence": thesis.get("thesis_confidence"),
        "thesis_reason": thesis.get("thesis_reason"),
        "thesis_broken_signals": thesis.get("thesis_broken_signals"),
        "thesis_intact_signals": thesis.get("thesis_intact_signals"),
        "momentum_state": momentum.get("momentum_state"),
        "momentum_confidence": momentum.get("momentum_confidence"),
        "momentum_reason": momentum.get("momentum_reason"),
        "recovery": recovery,
        "hard_boundary": hard_boundary,
        "preexisting_breach": hard_boundary.get("preexisting_breach"),
        "new_breach": hard_boundary.get("new_breach"),
        "profit_protection": profit_protection,
        "canonical_recommendation": recommendation,
        "human_readable_reason": "; ".join(reason_parts),
        "confidence": round(confidence, 4),
        "data_completeness": "complete" if not blockers else "incomplete",
        "exact_blockers": list(blockers),
        "provider_native_timestamp": inputs.get("provider_native_timestamp"),
        "provider_native_timestamp_provenance": inputs.get("provider_native_timestamp_provenance"),
        "provider_native_timestamp_source": inputs.get("provider_native_timestamp_source"),
        "evidence_provenance": {
            "entry_price_source": "broker_position_avg_entry_price" if broker_position and _num(broker_position.get("avg_entry_price")) else "position_entry_price",
            "current_price_source": "broker_position_current_price" if broker_position and _num(broker_position.get("current_price")) else "latest_price_snapshot",
            "ownership_source": "provided_ownership" if ownership_dict else "not_provided",
            "lane_recovery_source": inputs.get("lane_source") or "UNAVAILABLE",
            "horizon_recovery_source": inputs.get("horizon_source") or "UNAVAILABLE",
            "market_observation_timestamp": inputs.get("market_observation_timestamp") or "UNAVAILABLE",
            "retrieval_timestamp": inputs.get("retrieval_timestamp") or "UNAVAILABLE",
            "provider_native_timestamp": inputs.get("provider_native_timestamp") or "UNAVAILABLE",
            "provider_native_timestamp_provenance": inputs.get("provider_native_timestamp_provenance") or "UNAVAILABLE",
            "provider_native_timestamp_source": inputs.get("provider_native_timestamp_source") or "UNAVAILABLE",
            "market_observation_unavailable": bool(inputs.get("market_observation_unavailable")),
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
        pos,
        inputs,
        recommendation,
        state,
        thesis,
        momentum,
        recovery,
        hard_boundary,
        profit_protection,
        as_of,
    )
    decision["shadow_record"] = shadow

    return decision


def run_loss_containment_review_v1(
    positions: Sequence[Mapping[str, Any]],
    *,
    ownership_map: Mapping[str, Mapping[str, Any]] | None = None,
    broker_positions: Mapping[str, Mapping[str, Any]] | None = None,
    latest_price_by_symbol: Mapping[str, Mapping[str, Any]] | None = None,
    policy: Mapping[str, Any] | None = None,
    prior_state: Mapping[str, Any] | None = None,
    max_positions: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run a bounded advisory review across a set of positions.

    Produces a canonical envelope with lane summaries, position decisions,
    metrics, and deduplicated breach events. Does not submit orders.
    """
    as_of = _iso(now)
    policy = dict(policy or {})
    policy.setdefault("lane_thresholds", LANE_LOSS_THRESHOLDS)
    ownership_map = dict(ownership_map or {})
    broker_positions = dict(broker_positions or {})
    latest_price_by_symbol = dict(latest_price_by_symbol or {})
    prior_state = dict(prior_state or {})
    prior_decisions = dict(prior_state.get("decisions") or {})
    prior_events = dict(prior_state.get("events") or {})

    position_decisions: list[dict[str, Any]] = []
    lane_summaries: dict[str, dict[str, Any]] = {
        "DAY": {"positions_evaluated": 0, "healthy": 0, "early_reviews": 0, "mandatory_reviews": 0, "bounded_recoveries": 0, "hard_boundary_breaches": 0, "thesis_broken": 0, "profit_protection": 0, "incomplete_data": 0, "preexisting_breaches": 0, "new_breaches": 0},
        "SWING": {"positions_evaluated": 0, "healthy": 0, "early_reviews": 0, "mandatory_reviews": 0, "bounded_recoveries": 0, "hard_boundary_breaches": 0, "thesis_broken": 0, "profit_protection": 0, "incomplete_data": 0, "preexisting_breaches": 0, "new_breaches": 0},
        "CRYPTO": {"positions_evaluated": 0, "healthy": 0, "early_reviews": 0, "mandatory_reviews": 0, "bounded_recoveries": 0, "hard_boundary_breaches": 0, "thesis_broken": 0, "profit_protection": 0, "incomplete_data": 0, "preexisting_breaches": 0, "new_breaches": 0},
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
        latest = dict(latest_price_by_symbol.get(symbol) or {})
        prior_decision = dict(prior_decisions.get(pid) or {})
        prior_recovery = dict(prior_decision.get("recovery") or {})

        decision = evaluate_position_loss_containment_v1(
            row,
            ownership=ownership,
            broker_position=broker,
            latest_price=latest,
            policy=policy,
            prior_state={"decisions": {pid: prior_decision}, "events": prior_events},
            prior_recovery=prior_recovery,
            now=now,
        )
        position_decisions.append(decision)
        new_decisions[pid] = decision
        blockers_by_position[pid] = decision["exact_blockers"]

        lane = decision["lane"]
        if lane in lane_summaries:
            lane_summaries[lane]["positions_evaluated"] += 1
            if decision["threshold_state"] == "HEALTHY":
                lane_summaries[lane]["healthy"] += 1
            elif decision["threshold_state"] == "EARLY_REVIEW":
                lane_summaries[lane]["early_reviews"] += 1
            elif decision["threshold_state"] == "MANDATORY_REVIEW":
                lane_summaries[lane]["mandatory_reviews"] += 1
            elif decision["threshold_state"] == "BOUNDED_RECOVERY":
                lane_summaries[lane]["bounded_recoveries"] += 1
            elif decision["threshold_state"] == "HARD_BOUNDARY_BREACH":
                lane_summaries[lane]["hard_boundary_breaches"] += 1
            elif decision["threshold_state"] == "THESIS_BROKEN":
                lane_summaries[lane]["thesis_broken"] += 1
            elif decision["threshold_state"] == "PROTECT_PROFIT":
                lane_summaries[lane]["profit_protection"] += 1
            elif decision["threshold_state"] in ("DATA_INCOMPLETE_FAIL_CLOSED", "UNRESOLVED_FAIL_CLOSED"):
                lane_summaries[lane]["incomplete_data"] += 1

            if decision["hard_boundary"].get("preexisting_breach"):
                lane_summaries[lane]["preexisting_breaches"] += 1
            if decision["hard_boundary"].get("new_breach"):
                lane_summaries[lane]["new_breaches"] += 1

        if decision["hard_boundary"].get("new_breach"):
            event_id = _event_identity(pid, symbol, lane, as_of, "NEW_HARD_BOUNDARY_BREACH")
            if event_id not in prior_events:
                new_events[event_id] = {
                    "event_id": event_id,
                    "event_type": "NEW_HARD_BOUNDARY_BREACH",
                    "position_id": pid,
                    "symbol": symbol,
                    "lane": lane,
                    "observed_loss_pct": decision["current_return_pct"],
                    "hard_boundary_pct": decision["thresholds"]["hard_boundary_pct"],
                    "as_of": as_of,
                }

        # Preexisting breach record: write once per cycle only if not already recorded.
        if decision["hard_boundary"].get("preexisting_breach"):
            event_id = _event_identity(pid, symbol, lane, as_of, "PREEXISTING_HARD_BOUNDARY_BREACH")
            if event_id not in prior_events:
                new_events[event_id] = {
                    "event_id": event_id,
                    "event_type": "PREEXISTING_HARD_BOUNDARY_BREACH",
                    "position_id": pid,
                    "symbol": symbol,
                    "lane": lane,
                    "observed_loss_pct": decision["current_return_pct"],
                    "hard_boundary_pct": decision["thresholds"]["hard_boundary_pct"],
                    "as_of": as_of,
                }

    # Aggregate metrics.
    total_evaluated = len(position_decisions)
    metrics = {
        "positions_evaluated": total_evaluated,
        "healthy_positions": sum(s["healthy"] for s in lane_summaries.values()),
        "early_reviews": sum(s["early_reviews"] for s in lane_summaries.values()),
        "mandatory_reviews": sum(s["mandatory_reviews"] for s in lane_summaries.values()),
        "bounded_recoveries": sum(s["bounded_recoveries"] for s in lane_summaries.values()),
        "hard_boundary_breaches": sum(s["hard_boundary_breaches"] for s in lane_summaries.values()),
        "thesis_broken_positions": sum(s["thesis_broken"] for s in lane_summaries.values()),
        "profit_protection_recommendations": sum(s["profit_protection"] for s in lane_summaries.values()),
        "incomplete_data_fail_closed": sum(s["incomplete_data"] for s in lane_summaries.values()),
        "preexisting_breaches": sum(s["preexisting_breaches"] for s in lane_summaries.values()),
        "new_breaches": sum(s["new_breaches"] for s in lane_summaries.values()),
        "avoided_loss_estimate": None,
        "missed_rebound_estimate": None,
        "rebound_rate_after_review": None,
        "rebound_rate_after_hard_boundary_breach": None,
        "average_additional_loss_after_recommendation": None,
        "average_recovery_after_recommendation": None,
        "recommendation_age_minutes": None,
        "policy_version": POLICY_SCHEMA_VERSION,
        "evidence_sample_size": total_evaluated,
        "provisional_metrics": True,
    }

    # Deduplicated state to persist.
    merged_decisions = {**prior_decisions, **new_decisions}
    merged_events = {**prior_events, **new_events}
    # Retention bound: keep the most recent 500 decisions and 500 events.
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
        "source_freshness": "position_snapshot_and_broker_position",
        "positions_evaluated": total_evaluated,
        "max_positions": max(1, int(max_positions)),
        "lane_summaries": lane_summaries,
        "position_decisions": position_decisions,
        "metrics": metrics,
        "exact_blockers": blockers_by_position,
        "provenance": {
            "policy_source": "astra_loss_containment_engine_v1",
            "ownership_integration": "astra_legacy_quarantine_v1",
            "broker_position_source": "broker_position_by_symbol",
        },
        "retention": {
            "decision_retention_count": 500,
            "event_retention_count": 500,
            "bounded": True,
        },
        "health_status": "ok" if not any(blockers_by_position.values()) else "blocked_positions_present",
        "state": {
            "schema_version": "astra_loss_containment_state_v1",
            "decisions": merged_decisions,
            "events": merged_events,
            "as_of": as_of,
        },
    }
