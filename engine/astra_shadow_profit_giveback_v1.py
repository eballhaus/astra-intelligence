"""Shadow profit-giveback analysis.

Contained, deterministic, side-effect-free module owned by Kimi.
Evaluates how much unrealized profit has been given back and whether
exiting at configured giveback thresholds would have improved the outcome.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_profit_giveback_v1"

DEFAULT_GIVEBACK_LEVELS = [0.10, 0.15, 0.20, 0.25, 0.30]


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


def _completed_observations(
    observations: list[Mapping[str, Any]],
    cutoff: datetime | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for obs in observations or []:
        if not isinstance(obs, Mapping):
            continue
        if not _is_completed(obs):
            continue
        ts = _observation_timestamp(obs)
        if cutoff is not None and (ts is None or ts > cutoff):
            continue
        rows.append({**obs, "_ts": ts})
    rows.sort(key=lambda x: x["_ts"] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def _giveback_levels(evaluation: Mapping[str, Any]) -> list[float]:
    params = dict(evaluation.get("strategy_parameters") or {})
    levels = params.get("giveback_levels")
    if isinstance(levels, list):
        return [float(x) for x in levels if isinstance(x, (int, float)) and x > 0]
    return list(DEFAULT_GIVEBACK_LEVELS)


def _peak_price(evaluation: Mapping[str, Any], observations: list[dict[str, Any]]) -> float | None:
    """Best available peak price from MFE or observation high water mark."""
    signal_price = _num(evaluation.get("shadow_reference_price") or evaluation.get("hold_price_at_signal"))
    mfe_return = _num(evaluation.get("maximum_favorable_excursion_after_signal"))
    if signal_price is not None and signal_price > 0 and mfe_return is not None and mfe_return > 0:
        return signal_price * (1.0 + mfe_return)
    if observations:
        prices = [_num(o.get("market_price")) for o in observations]
        max_price = max((p for p in prices if p is not None), default=None)
        if max_price is not None and max_price > 0:
            return max_price
    return signal_price


def _current_price(
    evaluation: Mapping[str, Any],
    observations: list[dict[str, Any]],
) -> float | None:
    actual = _num(evaluation.get("actual_exit_price"))
    if actual is not None and actual > 0:
        return actual
    if observations:
        price = _num(observations[-1].get("market_price"))
        if price is not None and price > 0:
            return price
    return None


def evaluate_profit_giveback(
    evaluation: Mapping[str, Any],
    observations: list[Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate profit-giveback for a shadow evaluation.

    Returns status, giveback_state, and whether exiting at a giveback level,
    after bounded confirmation, or continuing hold was best.
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
        "peak_price": None,
        "maximum_unrealized_profit_dollars": None,
        "current_price": None,
        "current_unrealized_profit_dollars": None,
        "profit_given_back_pct": None,
        "profit_given_back_dollars": None,
        "giveback_levels_evaluated": [],
        "best_observed_policy": None,
        "profit_preserved": None,
        "additional_upside_missed": None,
        "drawdown_avoided": None,
        "net_profit_protection_value": None,
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

    completed = _completed_observations(observations, cutoff=now)
    result["sample_size"] = len(completed)

    peak_price = _peak_price(evaluation, completed)
    if peak_price is None or peak_price <= signal_price:
        result["status"] = "INSUFFICIENT_SAMPLE"
        result["blockers"].append("NO_POSITIVE_PEAK_PROFIT")
        return result
    result["peak_price"] = peak_price

    has_actual_exit = (_num(evaluation.get("actual_exit_price")) or 0) > 0
    if not completed and not has_actual_exit:
        result["status"] = "PENDING_OBSERVATION"
        result["blockers"].append("NO_COMPLETED_OBSERVATIONS")
        return result

    current_price = _current_price(evaluation, completed)
    if current_price is None or current_price <= 0:
        result["status"] = "INSUFFICIENT_SAMPLE"
        result["blockers"].append("NO_DEFENSIBLE_CURRENT_PRICE")
        return result
    result["current_price"] = current_price

    peak_profit = (peak_price - signal_price) * quantity
    current_profit = (current_price - signal_price) * quantity
    profit_given_back_dollars = (peak_price - current_price) * quantity
    profit_given_back_pct = profit_given_back_dollars / peak_profit if peak_profit != 0 else 0.0

    result["maximum_unrealized_profit_dollars"] = peak_profit
    result["current_unrealized_profit_dollars"] = current_profit
    result["profit_given_back_pct"] = profit_given_back_pct
    result["profit_given_back_dollars"] = profit_given_back_dollars

    levels = _giveback_levels(evaluation)
    candidates: list[dict[str, Any]] = []

    def _policy_value(exit_price: float) -> dict[str, Any]:
        exit_profit = (exit_price - signal_price) * quantity
        profit_preserved = exit_profit - current_profit
        upside_missed = -profit_preserved
        if upside_missed < 0:
            upside_missed = 0.0
        if profit_preserved < 0:
            profit_preserved = 0.0
        drawdown_avoided = profit_preserved
        net_value = profit_preserved - upside_missed
        return {
            "profit_preserved": profit_preserved,
            "upside_missed": upside_missed,
            "drawdown_avoided": drawdown_avoided,
            "net_value": net_value,
        }

    best_policy = "CONTINUE_HOLD"
    best_metrics = {
        "profit_preserved": 0.0,
        "upside_missed": 0.0,
        "drawdown_avoided": 0.0,
        "net_value": 0.0,
        "exit_price": current_price,
    }

    for level in levels:
        threshold_price = signal_price + (1.0 - level) * (peak_price - signal_price)
        triggered = False
        exit_price = current_price
        for obs in completed:
            price = _num(obs.get("market_price"))
            if price is None:
                continue
            if price <= threshold_price:
                triggered = True
                exit_price = price
                break
        metrics = _policy_value(exit_price)
        candidates.append({
            "level": level,
            "triggered": triggered,
            "threshold_price": threshold_price,
            "exit_price": exit_price,
            **metrics,
        })
        if metrics["net_value"] > best_metrics["net_value"]:
            best_policy = f"EXIT_AT_{int(level * 100)}PCT_GIVEBACK"
            best_metrics = {**metrics, "exit_price": exit_price}

    # Bounded confirmation: trigger must be confirmed by the next observation also at/below threshold.
    for cand in candidates:
        if not cand["triggered"]:
            continue
        threshold_price = cand["threshold_price"]
        confirmed = False
        exit_price = current_price
        for i in range(len(completed) - 1):
            price = _num(completed[i].get("market_price"))
            next_price = _num(completed[i + 1].get("market_price"))
            if price is None or next_price is None:
                continue
            if price <= threshold_price and next_price <= threshold_price:
                confirmed = True
                exit_price = next_price
                break
        if confirmed:
            metrics = _policy_value(exit_price)
            if metrics["net_value"] > best_metrics["net_value"]:
                best_policy = f"EXIT_AFTER_CONFIRMATION_{int(cand['level'] * 100)}PCT"
                best_metrics = {**metrics, "exit_price": exit_price}

    result["giveback_levels_evaluated"] = candidates
    result["best_observed_policy"] = best_policy
    result["profit_preserved"] = best_metrics["profit_preserved"]
    result["additional_upside_missed"] = best_metrics["upside_missed"]
    result["drawdown_avoided"] = best_metrics["drawdown_avoided"]
    result["net_profit_protection_value"] = best_metrics["net_value"]
    result["status"] = "COMPLETED" if has_actual_exit else "PARTIAL"
    return result
