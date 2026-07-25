"""Shadow exit regret analysis.

Contained, deterministic, side-effect-free module owned by Kimi.
Compares a shadow exit strategy against the realized hold path to quantify
late-exit regret (additional loss from not exiting) and early-exit regret
(upside missed by exiting).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_exit_regret_v1"


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
    *,
    position_identity: str,
    shadow_evaluation_id: str,
    signal_at: datetime,
    cutoff: datetime | None = None,
) -> list[dict[str, Any]]:
    """Return completed observations sorted by actual timestamp, optionally capped."""
    rows: list[dict[str, Any]] = []
    for obs in observations or []:
        if not isinstance(obs, Mapping):
            continue
        if not _is_completed(obs):
            continue
        ts = _observation_timestamp(obs)
        if _text(obs.get("position_identity")) != position_identity or _text(obs.get("shadow_evaluation_id")) != shadow_evaluation_id:
            continue
        if ts is None or ts < signal_at or (cutoff is not None and ts > cutoff):
            continue
        rows.append({**obs, "_ts": ts})
    rows.sort(key=lambda x: x["_ts"] or datetime.min.replace(tzinfo=timezone.utc))
    return rows


def _outcome_price(evaluation: Mapping[str, Any], observations: list[dict[str, Any]]) -> float | None:
    """Best available realized price: actual exit first, then latest completed observation."""
    actual_exit = _num(evaluation.get("actual_exit_price"))
    if actual_exit is not None and actual_exit > 0:
        return actual_exit
    if observations:
        price = _num(observations[-1].get("market_price"))
        if price is not None and price > 0:
            return price
    return None


def calculate_exit_regret(
    evaluation: Mapping[str, Any],
    observations: list[Mapping[str, Any]] | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Calculate shadow exit regret for a single evaluation.

    Sign convention:
      * positive net_exit_regret  -> chosen strategy was worse than the alternative
      * negative net_exit_regret  -> chosen strategy was better (benefit)
      * capital_preserved         -> positive amount the chosen strategy protected
      * capital_missed            -> positive amount the chosen strategy failed to capture
      * late_exit_regret          -> regret from holding through a drop (HOLD strategies)
      * early_exit_regret         -> regret from exiting before a rise (EXIT strategies)
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
        "outcome_price": None,
        "late_exit_regret": None,
        "early_exit_regret": None,
        "net_exit_regret": None,
        "capital_preserved": None,
        "capital_missed": None,
        "additional_loss_pct": None,
        "profit_missed_pct": None,
        "shadow_only": True,
        "execution_authority": "DISABLED",
        "promotion_status": "NOT_PROMOTED",
        "human_review_required": True,
        "generated_at": _iso(now),
    }

    identity = _text(evaluation.get("position_identity"))
    evaluation_id = _text(evaluation.get("shadow_evaluation_id"))
    if not identity or not evaluation_id:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_EVALUATION_IDENTITY")
        return result

    signal_price = _num(evaluation.get("shadow_reference_price") or evaluation.get("hold_price_at_signal"))
    if signal_price is None or signal_price <= 0:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_REFERENCE_PRICE")
        return result
    result["signal_price"] = signal_price

    signal_at = _parse(evaluation.get("shadow_reference_timestamp") or evaluation.get("generated_at"))
    if signal_at is None:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_SIGNAL_TIMESTAMP")
        return result

    quantity = _num(evaluation.get("quantity_at_evaluation"))
    if quantity is None or quantity <= 0:
        result["status"] = "INVALID_INPUT"
        result["blockers"].append("MISSING_OR_INVALID_QUANTITY")
        return result

    completed = _completed_observations(
        observations, position_identity=identity, shadow_evaluation_id=evaluation_id, signal_at=signal_at, cutoff=now,
    )
    if observations and not completed and any(
        isinstance(obs, Mapping) and _is_completed(obs)
        and (_text(obs.get("position_identity")) != identity or _text(obs.get("shadow_evaluation_id")) != evaluation_id)
        for obs in observations
    ):
        result["blockers"].append("IDENTITY_MISMATCH_REJECTED")
    result["sample_size"] = len(completed)

    has_actual_exit = (_num(evaluation.get("actual_exit_price")) or 0) > 0
    if not completed and not has_actual_exit:
        result["status"] = "PENDING_OBSERVATION"
        result["blockers"].append("NO_COMPLETED_OBSERVATIONS")
        return result

    outcome_price = _outcome_price(evaluation, completed)
    if outcome_price is None or outcome_price <= 0:
        result["status"] = "INSUFFICIENT_SAMPLE"
        result["blockers"].append("NO_DEFENSIBLE_OUTCOME_PRICE")
        return result
    result["outcome_price"] = outcome_price

    strategy = _text(evaluation.get("shadow_strategy")).upper()
    exit_strategies = {
        "EXIT_NOW", "EXIT_AFTER_CONFIRMATION", "PROTECT_PROFIT", "PROTECT_ON_BOUNCE",
        "THESIS_BREAK_EXIT", "MOMENTUM_DETERIORATION_EXIT", "HARD_DRAWDOWN_EXIT",
        "OPPORTUNITY_COST_REPLACEMENT",
    }
    is_exit_strategy = strategy in exit_strategies

    price_diff = outcome_price - signal_price
    pct_diff = price_diff / signal_price
    notional_diff = price_diff * quantity

    late_exit_regret: float | None = None
    early_exit_regret: float | None = None
    capital_preserved: float | None = None
    capital_missed: float | None = None
    additional_loss_pct: float | None = None
    profit_missed_pct: float | None = None

    if is_exit_strategy:
        if price_diff > 0:
            # Exiting early missed upside.
            capital_missed = notional_diff
            profit_missed_pct = pct_diff
            early_exit_regret = capital_missed
        elif price_diff < 0:
            # Exiting avoided further loss.
            capital_preserved = -notional_diff
            additional_loss_pct = -pct_diff
    elif strategy == "CONTINUE_HOLD":
        if price_diff < 0:
            # Holding too long incurred additional loss.
            capital_missed = -notional_diff
            additional_loss_pct = -pct_diff
            late_exit_regret = capital_missed
        elif price_diff > 0:
            # Holding captured upside that an exit would have missed.
            capital_preserved = notional_diff
            profit_missed_pct = pct_diff
    else:
        # Unknown strategy: produce symmetric measures without implying direction.
        if price_diff < 0:
            capital_missed = -notional_diff
            additional_loss_pct = -pct_diff
            late_exit_regret = capital_missed
        else:
            capital_missed = notional_diff
            profit_missed_pct = pct_diff
            early_exit_regret = capital_missed

    net_exit_regret = _num(capital_missed, 0.0) - _num(capital_preserved, 0.0)

    result.update({
        "late_exit_regret": late_exit_regret,
        "early_exit_regret": early_exit_regret,
        "net_exit_regret": net_exit_regret,
        "capital_preserved": capital_preserved,
        "capital_missed": capital_missed,
        "additional_loss_pct": additional_loss_pct,
        "profit_missed_pct": profit_missed_pct,
    })

    if has_actual_exit:
        result["status"] = "COMPLETED"
    elif result["sample_size"] > 0:
        result["status"] = "PARTIAL"
    else:
        result["status"] = "PENDING_OBSERVATION"
        result["blockers"].append("NO_COMPLETED_OBSERVATIONS")
    return result
