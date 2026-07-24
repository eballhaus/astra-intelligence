"""Bounded, advisory-only portfolio segmentation and legacy resolution.

This contract projects current canonical broker facts and existing advisory
signals.  It never changes position membership, creates an order, or infers
lane, horizon, or an original thesis.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_legacy_portfolio_resolution_v1"
RESOLUTION_PLANS = frozenset({
    "KEEP_UNDER_REVIEW", "PROTECT_ON_BOUNCE", "REDUCE_REVIEW",
    "FULL_EXIT_REVIEW", "REPLACE_WHEN_CAPACITY_NEEDED", "WAIT_FOR_EVIDENCE",
})


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _index(rows: list[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {
        _text(row.get("symbol")).upper(): dict(row)
        for row in rows or []
        if isinstance(row, Mapping) and _text(row.get("symbol"))
    }


def _position_value(row: Mapping[str, Any]) -> tuple[float, float, float]:
    market_value = _num(row.get("market_value") or row.get("marketValue"))
    cost_basis = _num(row.get("cost_basis") or row.get("costBasis"))
    unrealized = _num(row.get("unrealized_pl") or row.get("unrealizedPL"))
    if not unrealized and market_value and cost_basis:
        unrealized = market_value - cost_basis
    return market_value, cost_basis, unrealized


def _resolution_plan(triage: Mapping[str, Any], evidence: Mapping[str, Any]) -> tuple[str, str, str]:
    recommendation = _text(triage.get("recommendation")).upper() or "WATCH"
    missing = list(triage.get("evidence_missing") or [])
    momentum = _text((triage.get("evidence_used") or {}).get("momentum_state")).upper()
    if recommendation == "THESIS_BROKEN" or recommendation == "EXIT_REVIEW":
        return "FULL_EXIT_REVIEW", "URGENT_REVIEW", "material advisory review is required"
    if recommendation == "PROTECT_CAPITAL":
        return "REDUCE_REVIEW", "ELEVATED_REVIEW", "capital protection requires manual review"
    if recommendation == "REPLACE_CANDIDATE":
        return "REPLACE_WHEN_CAPACITY_NEEDED", "CAPACITY_RELEASE_REVIEW", "eligible replacement evidence is available"
    if missing:
        return "WAIT_FOR_EVIDENCE", "ELEVATED_REVIEW", "required evidence remains unavailable"
    if momentum in {"DETERIORATING", "WEAK", "NEGATIVE"}:
        return "PROTECT_ON_BOUNCE", "ELEVATED_REVIEW", "deteriorating momentum warrants a bounded review"
    if recommendation == "HOLD":
        return "KEEP_UNDER_REVIEW", "NORMAL_REVIEW", "current evidence supports continued monitoring"
    return "KEEP_UNDER_REVIEW", "NORMAL_REVIEW", "watch state requires periodic forward-value reassessment"


def build_legacy_portfolio_resolution_v1(
    broker_positions: Mapping[str, Mapping[str, Any]],
    recovery: Mapping[str, Any],
    *,
    triage: Mapping[str, Any] | None = None,
    evidence: Mapping[str, Any] | None = None,
    capacity_snapshot: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one current advisory record for every legacy broker position."""
    recovery_by_symbol = _index(list(recovery.get("positions") or []))
    triage_by_symbol = _index(list((triage or {}).get("positions") or []))
    evidence_by_symbol = _index(list((evidence or {}).get("positions") or []))
    total = {"market_value": 0.0, "cost_basis": 0.0, "unrealized_pl": 0.0, "count": 0}
    legacy = {"market_value": 0.0, "cost_basis": 0.0, "unrealized_pl": 0.0, "count": 0}
    managed = {"market_value": 0.0, "cost_basis": 0.0, "unrealized_pl": 0.0, "count": 0}
    rows: list[dict[str, Any]] = []
    capacity_by_plan = {plan: 0.0 for plan in RESOLUTION_PLANS}

    for key, raw in sorted((broker_positions or {}).items()):
        position = dict(raw or {})
        symbol = _text(position.get("symbol") or key).upper()
        recovery_row = recovery_by_symbol.get(symbol, {})
        lane_resolved = _text(recovery_row.get("lane_status")).upper() == "RESOLVED"
        horizon_resolved = _text(recovery_row.get("horizon_status")).upper() == "RESOLVED"
        is_managed = lane_resolved and horizon_resolved
        market_value, cost_basis, unrealized = _position_value(position)
        total["count"] += 1
        total["market_value"] += market_value
        total["cost_basis"] += cost_basis
        total["unrealized_pl"] += unrealized
        cohort = managed if is_managed else legacy
        cohort["count"] += 1
        cohort["market_value"] += market_value
        cohort["cost_basis"] += cost_basis
        cohort["unrealized_pl"] += unrealized
        if is_managed:
            continue
        triage_row, evidence_row = triage_by_symbol.get(symbol, {}), evidence_by_symbol.get(symbol, {})
        plan, urgency, reason = _resolution_plan(triage_row, evidence_row)
        capacity_by_plan[plan] += market_value
        replacement_state = _text(evidence_row.get("replacement_candidate_status")) or "NO_ELIGIBLE_REPLACEMENT"
        rows.append({
            "symbol": symbol,
            "triage_recommendation": _text(triage_row.get("recommendation")) or "WATCH",
            "resolution_plan": plan,
            "urgency": urgency,
            "confidence": _text(triage_row.get("confidence")) or "LOW",
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pl": round(unrealized, 2),
            "current_return_pct": round(_num(position.get("unrealized_plpc") or position.get("unrealized_return_pct")) * 100.0, 3),
            "forward_value_state": _text(evidence_row.get("opportunity_cost_status")) or "UNAVAILABLE",
            "momentum_state": _text((triage_row.get("evidence_used") or {}).get("momentum_state")) or "UNAVAILABLE",
            "catalyst_state": _text((triage_row.get("evidence_used") or {}).get("catalyst_state")) or "NO_CURRENT_CATALYST_EVIDENCE",
            "position_age_state": _text(evidence_row.get("position_age_status")) or "UNAVAILABLE",
            "capital_efficiency": "UNAVAILABLE" if not market_value else ("NEGATIVE_RETURN" if unrealized < 0 else "POSITIVE_RETURN"),
            "opportunity_cost_state": _text(evidence_row.get("opportunity_cost_status")) or "UNAVAILABLE",
            "replacement_state": replacement_state,
            "estimated_capacity_releasable": round(market_value, 2) if plan in {"REDUCE_REVIEW", "FULL_EXIT_REVIEW", "REPLACE_WHEN_CAPACITY_NEEDED"} else 0.0,
            "capacity_release_priority": urgency,
            "conditions_that_improve": ["fresh momentum and catalyst evidence", "improved forward-value evidence"],
            "conditions_that_worsen": ["continued loss with deteriorating momentum", "negative catalyst evidence", "superior eligible replacement"],
            "first_causal_blocker": _text(triage_row.get("first_causal_blocker")) or _text(evidence_row.get("first_causal_blocker")) or "LEGACY_METADATA_UNAVAILABLE",
            "plain_english_explanation": f"{plan}: {reason}.",
            "execution_authority": "DISABLED",
            "advisory_only": True,
        })

    def cohort_payload(source: Mapping[str, Any]) -> dict[str, Any]:
        cost = _num(source.get("cost_basis"))
        pnl = _num(source.get("unrealized_pl"))
        return {
            "position_count": int(source.get("count") or 0),
            "market_value": round(_num(source.get("market_value")), 2),
            "cost_basis": round(cost, 2),
            "unrealized_pl": round(pnl, 2),
            "unrealized_return_pct": round((pnl / cost) * 100.0, 3) if cost else None,
        }

    total_payload = cohort_payload(total)
    legacy_payload = cohort_payload(legacy)
    managed_payload = cohort_payload(managed)
    value = _num(total.get("market_value"))
    capacity = dict(capacity_snapshot or {})
    potentially_releasable = sum(
        row["estimated_capacity_releasable"] for row in rows
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now(),
        "total_broker_portfolio": total_payload,
        "legacy_portfolio": {**legacy_payload, "capital_consumed": legacy_payload["market_value"], "percentage_of_portfolio": round((legacy_payload["market_value"] / value) * 100.0, 3) if value else 0.0},
        "astra_managed_portfolio": managed_payload,
        "performance_population_contract": {
            "broker_portfolio_performance": "TOTAL_BROKER_PORTFOLIO",
            "legacy_portfolio_performance": "LEGACY_PORTFOLIO",
            "astra_strategy_performance": "ASTRA_MANAGED_PORTFOLIO_ONLY",
            "legacy_excluded_from_astra_managed_metrics": True,
        },
        "legacy_drag": {"unrealized_pl": legacy_payload["unrealized_pl"], "market_value": legacy_payload["market_value"]},
        "legacy_position_count": legacy_payload["position_count"],
        "resolution_plan_count": len(rows),
        "positions": rows,
        "capacity_recovery": {
            "legacy_capital_tied_up": legacy_payload["market_value"],
            "legacy_position_slots_occupied": legacy_payload["position_count"],
            "capital_by_resolution_plan": {key: round(value, 2) for key, value in sorted(capacity_by_plan.items())},
            "estimated_capacity_releasable": round(potentially_releasable, 2),
            "available_capacity_by_lane": dict(capacity.get("lanes") or {}),
            "eligible_opportunities_blocked_by_capacity": int(capacity.get("eligible_opportunities_blocked_by_capacity") or 0),
            "estimate_is_advisory_only": True,
        },
        "execution_authority": "DISABLED", "advisory_only": True,
        "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
        "state_mutations_from_get": 0, "paper_only_preserved": True,
    }


def save_legacy_portfolio_resolution_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    root = Path(state_dir)
    _atomic_write(root / "astra_portfolio_segmentation_v1.json", payload)
    _atomic_write(root / "astra_legacy_position_resolution_v1.json", payload)
    _atomic_write(root / "astra_legacy_capacity_recovery_v1.json", payload.get("capacity_recovery") or {})


def load_legacy_portfolio_resolution_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try:
        value = json.loads((Path(state_dir) / "astra_legacy_position_resolution_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(value) if isinstance(value, dict) else {}
