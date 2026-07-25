"""Deterministic, shadow-only aggregation of completed exit-analysis outputs."""
from __future__ import annotations

from collections import defaultdict
from math import isfinite
from typing import Any, Mapping


SCHEMA_VERSION = "astra_shadow_exit_performance_v1"
MIN_COMPARABLE_OUTCOMES = 3


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        result = float(value)
        return result if isfinite(result) else None
    except (TypeError, ValueError):
        return None


def _module_rows(outcome: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    modules = outcome.get("modules")
    if isinstance(modules, Mapping):
        return [value for _, value in sorted(modules.items()) if isinstance(value, Mapping)]
    return [outcome]


def _comparable(outcome: Mapping[str, Any]) -> tuple[bool, float | None, dict[str, float | None]]:
    if _text(outcome.get("status")).upper() != "COMPLETED":
        return False, None, {}
    # A module may finish a bounded observation window while its underlying
    # position remains open.  That is useful advisory evidence, but not a
    # finalized outcome for aggregate performance attribution.
    evaluation_status = _text(outcome.get("evaluation_status")).upper()
    if evaluation_status and evaluation_status != "COMPLETED":
        return False, None, {}
    values: dict[str, float | None] = {"late": None, "early": None, "net": None, "loss_avoided": None, "profit_missed": None, "capital_saved": None, "giveback": None}
    for module in _module_rows(outcome):
        if _text(module.get("status")).upper() != "COMPLETED":
            continue
        values["late"] = values["late"] if values["late"] is not None else _num(module.get("late_exit_regret"))
        values["early"] = values["early"] if values["early"] is not None else _num(module.get("early_exit_regret"))
        values["net"] = values["net"] if values["net"] is not None else _num(module.get("net_regret"))
        values["loss_avoided"] = values["loss_avoided"] if values["loss_avoided"] is not None else _num(module.get("additional_loss_avoided"))
        values["profit_missed"] = values["profit_missed"] if values["profit_missed"] is not None else _num(module.get("additional_upside_missed"))
        if values["capital_saved"] is None:
            capital_saved = _num(module.get("net_capital_saved"))
            values["capital_saved"] = capital_saved if capital_saved is not None else _num(module.get("net_profit_protection_value"))
        values["giveback"] = values["giveback"] if values["giveback"] is not None else _num(module.get("net_profit_protection_value"))
    net = values["capital_saved"]
    if net is None:
        net = values["net"]
    return net is not None, net, values


def _mean(values: list[float | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return round(sum(clean) / len(clean), 10) if clean else None


def _aggregate_group(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    completed, partial, pending, blocked, invalid = [], 0, 0, 0, 0
    values: list[dict[str, float | None]] = []
    returns: list[float] = []
    for row in rows:
        status = _text(row.get("status")).upper()
        if status in {"PENDING_OBSERVATION", "PARTIAL"}: partial += 1
        elif status == "EXTERNALLY_BLOCKED": blocked += 1
        elif status in {"INVALID_INPUT", "UNSUPPORTED_STRATEGY"}: invalid += 1
        comparable, net, measures = _comparable(row)
        if comparable:
            completed.append(row); values.append(measures); returns.append(float(net or 0.0))
        elif status not in {"PENDING_OBSERVATION", "PARTIAL", "EXTERNALLY_BLOCKED", "INVALID_INPUT", "UNSUPPORTED_STRATEGY"}:
            pending += 1
    gross_gain = sum(value for value in returns if value > 0)
    gross_loss = abs(sum(value for value in returns if value < 0))
    sample = len(completed)
    if sample < MIN_COMPARABLE_OUTCOMES:
        pf, pf_status, win_rate, win_rate_status = None, "INSUFFICIENT_SAMPLE", None, "INSUFFICIENT_SAMPLE"
    elif gross_loss == 0:
        pf, pf_status = None, "ZERO_GROSS_LOSS"
        win_rate, win_rate_status = sum(1 for value in returns if value > 0) / sample, "AVAILABLE"
    else:
        pf, pf_status = round(gross_gain / gross_loss, 10), "AVAILABLE"
        win_rate, win_rate_status = sum(1 for value in returns if value > 0) / sample, "AVAILABLE"
    return {
        "evaluation_count": len(rows), "completed_outcome_count": sample, "partial_outcome_count": partial,
        "pending_count": pending, "externally_blocked_count": blocked, "invalid_count": invalid, "sample_size": sample,
        "confidence_status": "DESCRIPTIVE" if sample >= MIN_COMPARABLE_OUTCOMES else "INSUFFICIENT_SAMPLE",
        "average_late_exit_regret": _mean([value.get("late") for value in values]), "average_early_exit_regret": _mean([value.get("early") for value in values]),
        "average_net_exit_regret": _mean([value.get("net") for value in values]), "average_loss_avoided": _mean([value.get("loss_avoided") for value in values]),
        "average_profit_missed": _mean([value.get("profit_missed") for value in values]), "average_capital_preserved": _mean([max(0.0, value.get("capital_saved") or 0.0) for value in values]),
        "average_net_capital_saved": _mean([value.get("capital_saved") for value in values]),
        "shadow_win_rate": win_rate, "shadow_win_rate_status": win_rate_status, "shadow_average_return": _mean(returns),
        "shadow_profit_factor": pf, "shadow_profit_factor_status": pf_status,
        "profit_gross": gross_gain, "loss_gross": gross_loss, "wins": sum(1 for value in returns if value > 0), "losses": sum(1 for value in returns if value < 0), "ties": sum(1 for value in returns if value == 0),
    }


def aggregate_shadow_exit_performance(outcomes: list[Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Aggregate only finalized, contract-valid shadow outputs without promotion."""
    valid = [dict(row) for row in list(outcomes or []) if isinstance(row, Mapping)]
    groups: dict[str, dict[str, list[Mapping[str, Any]]]] = {name: defaultdict(list) for name in ("strategy", "signal_family", "lane", "horizon", "legacy_population", "market_regime", "sector_regime", "volatility_regime")}
    for row in valid:
        legacy = _text(row.get("legacy_status")).upper() == "LEGACY"
        values = {
            "strategy": _text(row.get("shadow_strategy") or "UNAVAILABLE"), "signal_family": _text(row.get("exit_signal_type") or "UNAVAILABLE"),
            "lane": "UNAVAILABLE" if legacy else _text(row.get("lane") or "UNAVAILABLE"), "horizon": "UNAVAILABLE" if legacy else _text(row.get("horizon") or "UNAVAILABLE"),
            "legacy_population": "LEGACY" if legacy else "CANONICAL", "market_regime": _text(row.get("market_regime") or "UNAVAILABLE"),
            "sector_regime": _text(row.get("sector_regime") or "UNAVAILABLE"), "volatility_regime": _text(row.get("volatility_regime") or "UNAVAILABLE"),
        }
        for group, key in values.items(): groups[group][key].append(row)
    by_group = {group: [{"key": key, **_aggregate_group(rows)} for key, rows in sorted(bucket.items())] for group, bucket in groups.items()}
    global_metrics = _aggregate_group(valid)
    return {
        "schema_version": SCHEMA_VERSION, "status": "COMPLETED" if global_metrics["sample_size"] >= MIN_COMPARABLE_OUTCOMES else "INSUFFICIENT_SAMPLE",
        "blockers": [] if global_metrics["sample_size"] >= MIN_COMPARABLE_OUTCOMES else ["MINIMUM_COMPARABLE_SAMPLE_NOT_MET"],
        "sample_size": global_metrics["sample_size"], "metrics": global_metrics, "global": global_metrics, "by_group": by_group,
        "shadow_only": True, "execution_authority": "DISABLED", "promotion_status": "NOT_PROMOTED", "human_review_required": True,
    }
