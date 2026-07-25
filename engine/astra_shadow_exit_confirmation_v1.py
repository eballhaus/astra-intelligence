"""Bounded, non-executing confirmation-path analysis for shadow exits."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_exit_confirmation_v1"
DEFAULT_CONFIRMATION_WINDOW_MINUTES = 60
DEFAULT_CONFIRMATION_THRESHOLD_PCT = 0.01
MAX_CONFIRMATION_WINDOW = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return (value or _now()).isoformat().replace("+00:00", "Z")


def _parse(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc) if value else None
    except (TypeError, ValueError):
        return None


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    except (TypeError, ValueError):
        return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _safe_param(evaluation: Mapping[str, Any], key: str, default: float) -> float:
    value = _num(dict(evaluation.get("strategy_parameters") or {}).get(key))
    return value if value is not None else default


def _deadline(evaluation: Mapping[str, Any], signal_at: datetime) -> datetime:
    explicit = _parse(evaluation.get("confirmation_deadline"))
    if explicit is not None:
        return min(max(explicit, signal_at), signal_at + MAX_CONFIRMATION_WINDOW)
    minutes = max(1.0, min(_safe_param(evaluation, "confirmation_window_minutes", DEFAULT_CONFIRMATION_WINDOW_MINUTES), MAX_CONFIRMATION_WINDOW.total_seconds() / 60.0))
    return signal_at + timedelta(minutes=minutes)


def _completed_rows(evaluation: Mapping[str, Any], observations: list[Mapping[str, Any]], signal_at: datetime, deadline: datetime, now: datetime) -> tuple[list[dict[str, Any]], list[str]]:
    identity = _text(evaluation.get("position_identity"))
    evaluation_id = _text(evaluation.get("shadow_evaluation_id"))
    rows, blockers = [], []
    seen: set[tuple[str, float]] = set()
    for observation in observations:
        if not isinstance(observation, Mapping) or _text(observation.get("observation_status")).upper() != "COMPLETED":
            continue
        observation_identity = _text(observation.get("position_identity"))
        observation_evaluation = _text(observation.get("shadow_evaluation_id"))
        if observation_identity != identity or observation_evaluation != evaluation_id:
            blockers.append("IDENTITY_MISMATCH_REJECTED")
            continue
        timestamp = _parse(observation.get("actual_observation_timestamp") or observation.get("market_evidence_at"))
        price = _num(observation.get("market_price"))
        if timestamp is None or price is None or price <= 0:
            blockers.append("MALFORMED_OBSERVATION_REJECTED")
            continue
        if timestamp > now:
            blockers.append("FUTURE_OBSERVATION_REJECTED")
            continue
        if timestamp < signal_at or timestamp > deadline:
            blockers.append("OUT_OF_WINDOW_OBSERVATION_REJECTED")
            continue
        key = (_iso(timestamp), price)
        if key in seen:
            blockers.append("DUPLICATE_OBSERVATION_REJECTED")
            continue
        seen.add(key)
        rows.append({"timestamp": timestamp, "price": price, "observation_id": _text(observation.get("shadow_observation_id"))})
    rows.sort(key=lambda row: (row["timestamp"], row["observation_id"]))
    return rows, sorted(set(blockers))


def evaluate_confirmation_path(
    evaluation: Mapping[str, Any], observations: list[Mapping[str, Any]] | None = None, *, now: datetime | None = None,
) -> dict[str, Any]:
    """Compare immediate exit, bounded confirmation exit, and continued hold.

    This is an observational calculation.  It never extends its deadline and
    ignores all evidence outside the finite signal-to-deadline interval.
    """
    evaluation, now = dict(evaluation or {}), now or _now()
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "shadow_evaluation_id": _text(evaluation.get("shadow_evaluation_id")),
        "position_identity": _text(evaluation.get("position_identity")),
        "symbol": _text(evaluation.get("symbol")), "asset_class": _text(evaluation.get("asset_class")),
        "shadow_strategy": _text(evaluation.get("shadow_strategy")), "lane": _text(evaluation.get("lane") or "UNAVAILABLE"),
        "horizon": _text(evaluation.get("horizon") or "UNAVAILABLE"), "legacy_status": _text(evaluation.get("legacy_status") or "UNKNOWN"),
        "status": "INSUFFICIENT_SAMPLE", "blockers": [], "sample_size": 0,
        "signal_price": None, "confirmation_deadline": None, "confirmation_observations_used": 0,
        "confirmation_signal_met": False, "confirmation_signal_failed": False, "confirmation_status": "INSUFFICIENT_EVIDENCE", "confirmation_state": "INSUFFICIENT_EVIDENCE",
        "confirmation_timestamp": None, "confirmation_exit_price": None,
        "immediate_exit_result": None, "confirmation_exit_result": None, "continue_hold_result": None,
        "additional_loss_avoided": None, "rebound_preserved": None, "rebound_missed": None,
        "time_to_decision": None, "estimated_slippage": None, "net_capital_saved": None,
        "best_observed_path": "INSUFFICIENT_EVIDENCE", "shadow_only": True,
        "execution_authority": "DISABLED", "promotion_status": "NOT_PROMOTED", "human_review_required": True,
        "generated_at": _iso(now),
    }
    identity = result["position_identity"]
    if not identity or not result["shadow_evaluation_id"]:
        result.update(status="INVALID_INPUT", blockers=["MISSING_EVALUATION_IDENTITY"])
        return result
    signal_price = _num(evaluation.get("shadow_reference_price") or evaluation.get("hold_price_at_signal"))
    quantity = _num(evaluation.get("quantity_at_evaluation"))
    signal_at = _parse(evaluation.get("shadow_reference_timestamp") or evaluation.get("generated_at"))
    if signal_price is None or signal_price <= 0:
        result.update(status="INVALID_INPUT", blockers=["MISSING_REFERENCE_PRICE"])
        return result
    if quantity is None or quantity <= 0:
        result.update(status="INVALID_INPUT", blockers=["MISSING_OR_INVALID_QUANTITY"])
        return result
    if signal_at is None:
        result.update(status="INVALID_INPUT", blockers=["MISSING_SIGNAL_TIMESTAMP"])
        return result
    deadline = _deadline(evaluation, signal_at)
    result.update(signal_price=signal_price, confirmation_deadline=_iso(deadline), estimated_slippage=max(0.0, _safe_param(evaluation, "estimated_slippage", 0.0)))
    rows, rejected = _completed_rows(evaluation, list(observations or []), signal_at, deadline, now)
    result["blockers"] = rejected
    result["sample_size"] = result["confirmation_observations_used"] = len(rows)
    if not rows:
        if now < deadline:
            result.update(status="PENDING_OBSERVATION", confirmation_status="PENDING_OBSERVATION", confirmation_state="PENDING_OBSERVATION")
            result["blockers"].append("CONFIRMATION_WINDOW_PENDING")
        else:
            result.update(status="INSUFFICIENT_SAMPLE", confirmation_status="INSUFFICIENT_EVIDENCE", confirmation_state="INSUFFICIENT_EVIDENCE")
            result["blockers"].append("NO_COMPLETED_OBSERVATIONS_IN_WINDOW")
        result["blockers"] = sorted(set(result["blockers"]))
        return result
    threshold_pct = max(0.0, min(_safe_param(evaluation, "confirmation_threshold_pct", DEFAULT_CONFIRMATION_THRESHOLD_PCT), 0.99))
    threshold_price = signal_price * (1.0 - threshold_pct)
    confirmation = next((row for row in rows if row["price"] <= threshold_price), None)
    final_price = rows[-1]["price"]
    immediate = 0.0
    continuation = (final_price - signal_price) / signal_price
    result.update(immediate_exit_result=immediate, continue_hold_result=continuation)
    if confirmation is None:
        result["confirmation_signal_failed"] = now >= deadline
        result["confirmation_status"] = "NOT_MET" if now >= deadline else "PENDING_OBSERVATION"
        result["confirmation_state"] = result["confirmation_status"]
        result["confirmation_exit_result"] = continuation
        result["best_observed_path"] = "CONTINUE_HOLD_BETTER" if continuation > 0 else "IMMEDIATE_EXIT_BETTER" if continuation < 0 else "INCONCLUSIVE"
        result["status"] = "COMPLETED" if now >= deadline else "PARTIAL"
        return result
    confirmation_return = (confirmation["price"] - signal_price) / signal_price
    slippage = result["estimated_slippage"]
    confirmation_return -= slippage / signal_price if signal_price else 0.0
    result.update(
        confirmation_signal_met=True, confirmation_status="MET", confirmation_state="MET", confirmation_timestamp=_iso(confirmation["timestamp"]),
        confirmation_exit_price=confirmation["price"], confirmation_exit_result=confirmation_return,
        time_to_decision=(confirmation["timestamp"] - signal_at).total_seconds() / 60.0,
        additional_loss_avoided=max(0.0, confirmation_return - continuation) * signal_price * quantity,
        rebound_preserved=max(0.0, continuation - confirmation_return) * signal_price * quantity,
        rebound_missed=max(0.0, continuation - confirmation_return) * signal_price * quantity,
        net_capital_saved=(confirmation_return - continuation) * signal_price * quantity,
    )
    paths = {"IMMEDIATE_EXIT_BETTER": immediate, "CONFIRMATION_EXIT_BETTER": confirmation_return, "CONTINUE_HOLD_BETTER": continuation}
    best = max(paths.values())
    winners = sorted(name for name, value in paths.items() if value == best)
    result["best_observed_path"] = winners[0] if len(winners) == 1 else "INCONCLUSIVE"
    result["status"] = "COMPLETED"
    return result
