"""Shadow bounce-back analysis.

Contained, deterministic, side-effect-free module owned by Kimi.
Compares EXIT_NOW, PROTECT_ON_BOUNCE, and CONTINUE_HOLD for a shadow
evaluation, detecting qualifying rebounds within a bounded wait window.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_bounce_back_v1"

_WINDOW_UNITS: dict[str, timedelta] = {
    "5m": timedelta(minutes=5),
    "15m": timedelta(minutes=15),
    "30m": timedelta(minutes=30),
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "12h": timedelta(hours=12),
    "1d": timedelta(days=1),
    "3d": timedelta(days=3),
    "5d": timedelta(days=5),
    "10d": timedelta(days=10),
    "close": timedelta(days=1),
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _num(value: Any, fallback: float | None = None) -> float | None:
    try:
        result = float(value)
        if result != result or abs(result) == float("inf"):
            return fallback
        return result
    except (TypeError, ValueError):
        return fallback


def _text(value: Any) -> str:
    return str(value or "").strip()


def _is_completed(obs: Mapping[str, Any]) -> bool:
    return _text(obs.get("observation_status")).upper() == "COMPLETED"


def _observation_timestamp(obs: Mapping[str, Any]) -> datetime | None:
    return _parse(obs.get("actual_observation_timestamp") or obs.get("market_evidence_at"))


def _window_delta(window: str) -> timedelta:
    return _WINDOW_UNITS.get(window, timedelta(hours=1))


def _wait_window(evaluation: Mapping[str, Any], default_window: str = "1h") -> tuple[timedelta, str]:
    """Return the bounded wait window for bounce detection."""
    windows = list(evaluation.get("required_observation_windows") or [])
    chosen = windows[0] if windows else default_window
    params = dict(evaluation.get("strategy_parameters") or {})
    if params.get("bounce_wait_window"):
        chosen = _text(params["bounce_wait_window"])
    return _window_delta(chosen), chosen


def _param(evaluation: Mapping[str, Any], key: str, default: float) -> float:
    params = dict(evaluation.get("strategy_parameters") or {})
    value = _num(params.get(key))
    return value if value is not None else default


def _completed_observations_in_window(
    observations: list[Mapping[str, Any]],
    signal_at: datetime,
    window: timedelta,
    cutoff: datetime | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    deadline = signal_at + window
    if cutoff is not None:
        deadline = min(deadline, cutoff)
    for obs in observations or []:
        if not isinstance(obs, Mapping):
            continue
        if not _is_completed(obs):
            continue
        ts = _observation_timestamp(obs)
        if ts is None or ts < signal_at or ts > deadline:
            continue
        rows.append({**obs, "_ts": ts})
    rows.sort(key=lambda x: x["_ts"])
    return rows


def evaluate_bounce_back(
    evaluation: Mapping[str, Any],
    observations: list[Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate bounce-back potential for a shadow evaluation.

    Returns status, bounce_state, capital recovered/lost, and a classification
    of whether immediate exit, bounce wait, or continue hold was best.
    """
    evaluation = dict(evaluation or {})
    observations = list(observations or [])
    now = now or _now()

    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "shadow_evaluation_id": _text(evaluation.get("shadow_evaluation_id")),
        "position_identity": _text(evaluation.get("position_identity")),
        "symbol": _text(evaluation.get("symbol")),
        "asset_class": _text(evaluation.get("asset_class")),
        "shadow_strategy": _text(evaluation.get("shadow_strategy")),
        "status": "INSUFFICIENT_SAMPLE",
        "blockers": [],
        "sample_size": 0,
        "signal_price": None,
        "wait_window": None,
        "rebound_threshold_pct": None,
        "max_additional_drawdown_pct": None,
        "rebound_occurred": False,
        "rebound_start_at": None,
        "rebound_peak_price": None,
        "rebound_percentage": None,
        "time_to_rebound": None,
        "maximum_additional_loss_before_rebound": None,
        "rebound_exit_price": None,
        "capital_recovered": None,
        "capital_lost_by_waiting": None,
        "immediate_exit_result": None,
        "bounce_wait_result": None,
        "continue_hold_result": None,
        "net_bounce_benefit": None,
        "bounce_state": None,
        "shadow_only": True,
        "execution_authority": "DISABLED",
        "promotion_status": "NOT_PROMOTED",
        "generated_at": _iso(now),
    }

    identity = _text(evaluation.get("position_identity"))
    if not identity:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_POSITION_IDENTITY")
        return result

    if _text(evaluation.get("legacy_status")).upper() == "LEGACY":
        result["status"] = "UNAVAILABLE"
        result["bounce_state"] = "LEGACY_POSITION"
        result["blockers"].append("LEGACY_POSITION_BOUNCE_UNAVAILABLE")
        return result

    signal_price = _num(evaluation.get("shadow_reference_price") or evaluation.get("hold_price_at_signal"))
    if signal_price is None or signal_price <= 0:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_REFERENCE_PRICE")
        return result
    result["signal_price"] = signal_price

    quantity = _num(evaluation.get("quantity_at_evaluation"))
    if quantity is None or quantity <= 0:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_OR_INVALID_QUANTITY")
        return result

    signal_at = _parse(evaluation.get("shadow_reference_timestamp") or evaluation.get("generated_at")) or now
    window_delta, window_name = _wait_window(evaluation)
    result["wait_window"] = window_name

    rebound_threshold_pct = _param(evaluation, "rebound_threshold_pct", 0.02)
    max_drawdown_pct = _param(evaluation, "max_additional_drawdown_pct", 0.05)
    result["rebound_threshold_pct"] = rebound_threshold_pct
    result["max_additional_drawdown_pct"] = max_drawdown_pct

    rows = _completed_observations_in_window(observations, signal_at, window_delta, cutoff=now)
    result["sample_size"] = len(rows)

    if not rows:
        result["status"] = "PENDING_OBSERVATION"
        result["blockers"].append("NO_COMPLETED_OBSERVATIONS_IN_WINDOW")
        return result

    prices = [_num(r.get("market_price")) for r in rows]
    if any(p is None or p <= 0 for p in prices):
        result["status"] = "INSUFFICIENT_SAMPLE"
        result["blockers"].append("INVALID_OBSERVATION_PRICE")
        return result

    final_price = prices[-1]
    min_price = min(prices)
    max_price = max(prices)

    immediate_return = 0.0
    hold_return = (final_price - signal_price) / signal_price
    result["immediate_exit_result"] = immediate_return
    result["continue_hold_result"] = hold_return

    # Detect rebound: a rise from a trough of at least rebound_threshold_pct,
    # occurring within the bounded window and without exceeding max drawdown.
    rebound_triggered = False
    rebound_trough: float | None = None
    rebound_peak: float | None = None
    rebound_ts: datetime | None = None
    max_drawdown_price = signal_price * (1.0 - max_drawdown_pct)

    trough = signal_price
    trough_ts = signal_at
    for row, price in zip(rows, prices):
        if price < trough:
            trough = price
            trough_ts = row["_ts"]
        if price <= max_drawdown_price:
            # Excessive drawdown invalidates bounce wait.
            break
        required_peak = trough * (1.0 + rebound_threshold_pct)
        if price >= required_peak and trough < signal_price:
            rebound_triggered = True
            rebound_trough = trough
            rebound_peak = price
            rebound_ts = row["_ts"]
            # Continue scanning for the highest subsequent price in the rebound.
            for later_row, later_price in zip(rows[rows.index(row):], prices[rows.index(row):]):
                if later_price >= rebound_peak:
                    rebound_peak = later_price
                    rebound_ts = later_row["_ts"]
            break

    if rebound_triggered and rebound_trough is not None and rebound_peak is not None and rebound_ts is not None:
        result["rebound_occurred"] = True
        result["rebound_start_at"] = _iso(rebound_ts)
        result["rebound_peak_price"] = rebound_peak
        result["rebound_percentage"] = (rebound_peak - rebound_trough) / rebound_trough
        result["time_to_rebound"] = (rebound_ts - signal_at).total_seconds() / 60.0
        result["maximum_additional_loss_before_rebound"] = signal_price - rebound_trough
        result["rebound_exit_price"] = rebound_peak
        result["capital_recovered"] = (rebound_peak - rebound_trough) * quantity
        result["capital_lost_by_waiting"] = (signal_price - rebound_trough) * quantity
        bounce_return = (rebound_peak - signal_price) / signal_price
    else:
        # No qualifying rebound: bounce-wait degenerates to continue hold.
        bounce_return = hold_return
        result["capital_lost_by_waiting"] = (signal_price - min_price) * quantity

    result["bounce_wait_result"] = bounce_return
    result["net_bounce_benefit"] = (bounce_return - immediate_return) * signal_price * quantity

    candidates = {
        "IMMEDIATE_EXIT": immediate_return,
        "BOUNCE_WAIT": bounce_return,
        "CONTINUE_HOLD": hold_return,
    }
    best_value = max(candidates.values())
    best_paths = {k for k, v in candidates.items() if v == best_value}

    if best_paths == {"IMMEDIATE_EXIT", "BOUNCE_WAIT", "CONTINUE_HOLD"}:
        bounce_state = "INCONCLUSIVE"
    elif "IMMEDIATE_EXIT" in best_paths:
        bounce_state = "IMMEDIATE_EXIT_BETTER"
    elif "CONTINUE_HOLD" in best_paths:
        bounce_state = "HOLD_BETTER"
    else:
        bounce_state = "BOUNCE_WAIT_BETTER"

    result["bounce_state"] = bounce_state
    result["status"] = "COMPLETED"
    return result
