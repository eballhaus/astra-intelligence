"""Canonical legacy-position quarantine, decision ownership, and exit readiness.

This module is additive and fail-closed. It never submits a broker order, never
activates the legacy SWING canary, and never changes DAY or CRYPTO execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _resolve_lane_from_row(row: Mapping[str, Any]) -> str:
    """Return the canonical lane id for a position, or empty if unresolvable."""
    r = dict(row or {})
    # Crypto lane takes precedence when asset class is explicit.
    asset_class = _text(r.get("asset_class") or r.get("asset_type")).lower()
    if asset_class in {"crypto", "cryptocurrency"}:
        return "CRYPTO"
    # Explicit canonical lane.
    lane = _text(r.get("lane_id")).upper()
    if lane in {"DAY", "SWING", "CRYPTO"}:
        return lane
    # Infer from horizon or style evidence.
    horizon = _text(
        r.get("paper_entry_horizon_style")
        or r.get("trade_horizon_style")
        or r.get("best_horizon_style")
        or r.get("intended_horizon")
        or r.get("original_horizon")
    ).lower()
    if horizon in {"scalp", "day_trade", "day", "intraday", "daytrading"}:
        return "DAY"
    if horizon in {"swing_trade", "swing", "position_trade", "position"}:
        return "SWING"
    # Explicit strategy cohort may override.
    cohort = _text(r.get("strategy_cohort")).lower()
    if "crypto" in cohort:
        return "CRYPTO"
    if "day" in cohort and "swing" not in cohort:
        return "DAY"
    if "swing" in cohort:
        return "SWING"
    return ""


def _is_active_strategy_owner(row: Mapping[str, Any]) -> bool:
    """Check whether the position has a non-empty, non-legacy lane owner."""
    r = dict(row or {})
    position_owner = _text(r.get("position_owner"))
    exit_owner = _text(r.get("exit_policy_owner") or r.get("exit_owner"))
    # Empty owners are not acceptable for active strategy attribution.
    if not position_owner and not exit_owner:
        return False
    # Legacy or canary ownership is not active strategy attribution.
    owner_text = f"{position_owner} {exit_owner}".upper()
    if "LEGACY" in owner_text or "CANARY" in owner_text:
        return False
    # Explicit legacy flag from the overlay.
    if bool(r.get("legacy_forward_only_management")) or bool(r.get("legacy_resolution_approved")):
        return False
    return True


def _has_legacy_owner(row: Mapping[str, Any]) -> bool:
    """Detect legacy or canary ownership regardless of cohort."""
    r = dict(row or {})
    position_owner = _text(r.get("position_owner")).upper()
    exit_owner = _text(r.get("exit_policy_owner") or r.get("exit_owner")).upper()
    return "LEGACY" in position_owner or "LEGACY" in exit_owner or "CANARY" in position_owner or "CANARY" in exit_owner


def resolve_canonical_position_ownership_v1(
    position: Mapping[str, Any],
    *,
    cohort: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Resolve every open position to a single canonical ownership state.

    Returns one of:
        ACTIVE_DAY, ACTIVE_SWING, ACTIVE_CRYPTO,
        LEGACY_QUARANTINED, DUST_REVIEW, BROKER_RESIDUE_REVIEW,
        UNRESOLVED_FAIL_CLOSED.

    Legacy positions remain included in total account P/L, capital, risk,
    and concentration. They are only separated from active-strategy attribution.
    """
    row = dict(position or {})
    cohort_info = dict(cohort or {})
    cohort_label = _text(cohort_info.get("cohort") or row.get("cohort")).upper()
    position_id = _text(cohort_info.get("position_id") or row.get("position_id") or row.get("asset_id") or row.get("symbol"))
    symbol = _text(row.get("symbol")).upper()
    quantity = abs(_num(row.get("qty") or row.get("quantity")) or 0.0)
    market_value = abs(_num(row.get("market_value")) or 0.0)
    broker_id = _text(row.get("asset_id") or row.get("position_id") or row.get("symbol"))
    lane = _resolve_lane_from_row(row)
    active_owner = _is_active_strategy_owner(row)
    legacy_overlay = bool(row.get("legacy_forward_only_management") or row.get("legacy_resolution_approved"))
    is_legacy_cohort = cohort_label.startswith("LEGACY") or legacy_overlay
    legacy_owner = _has_legacy_owner(row)

    # Legacy owner detection is authoritative and precedes lane attribution.
    if legacy_owner and not (quantity <= 0 or market_value < 0.01):
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "LEGACY_QUARANTINED",
            "lane": lane or "UNKNOWN",
            "cohort": cohort_label,
            "active_strategy": False,
            "legacy_quarantined": True,
            "broker_residue": False,
            "dust": False,
            "unresolved": False,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": True,
            "reason": "position_owner_or_exit_policy_owner_is_legacy_or_canary",
            "as_of": _iso(),
        }

    # Dust is detected before any other classification.
    if quantity <= 0 or market_value < 0.01 or cohort_label == "DUST_POSITION":
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "DUST_REVIEW",
            "lane": lane,
            "cohort": cohort_label or "DUST_POSITION",
            "active_strategy": False,
            "legacy_quarantined": False,
            "broker_residue": False,
            "dust": True,
            "unresolved": False,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": False,
            "reason": "quantity_or_market_value_below_dust_threshold",
            "as_of": _iso(),
        }

    # Broker residue: no authoritative broker identifier.
    if not broker_id or cohort_label == "BROKER_RESIDUE_POSITION":
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "BROKER_RESIDUE_REVIEW",
            "lane": lane,
            "cohort": cohort_label or "BROKER_RESIDUE_POSITION",
            "active_strategy": False,
            "legacy_quarantined": False,
            "broker_residue": True,
            "dust": False,
            "unresolved": False,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": False,
            "reason": "no_authoritative_broker_identifier",
            "as_of": _iso(),
        }

    # Legacy quarantine: cohort or overlay marks it as legacy, regardless of lane.
    if is_legacy_cohort:
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "LEGACY_QUARANTINED",
            "lane": lane or "UNKNOWN",
            "cohort": cohort_label,
            "active_strategy": False,
            "legacy_quarantined": True,
            "broker_residue": False,
            "dust": False,
            "unresolved": False,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": True,
            "reason": "position_cohort_or_overlay_marked_legacy",
            "as_of": _iso(),
        }

    # Active strategy attribution requires a valid lane and valid owner.
    if not lane:
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "UNRESOLVED_FAIL_CLOSED",
            "lane": "",
            "cohort": cohort_label,
            "active_strategy": False,
            "legacy_quarantined": False,
            "broker_residue": False,
            "dust": False,
            "unresolved": True,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": False,
            "reason": "lane_unresolvable_and_not_legacy",
            "as_of": _iso(),
        }

    if not active_owner:
        return {
            "schema_version": "astra_canonical_position_ownership_v1",
            "position_id": position_id,
            "symbol": symbol,
            "ownership": "UNRESOLVED_FAIL_CLOSED",
            "lane": lane,
            "cohort": cohort_label,
            "active_strategy": False,
            "legacy_quarantined": False,
            "broker_residue": False,
            "dust": False,
            "unresolved": True,
            "included_in_total_exposure": True,
            "included_in_active_strategy": False,
            "included_in_legacy_quarantine": False,
            "reason": "empty_or_legacy_owner_rejects_active_strategy_attribution",
            "as_of": _iso(),
        }

    if lane == "DAY":
        ownership = "ACTIVE_DAY"
    elif lane == "CRYPTO":
        ownership = "ACTIVE_CRYPTO"
    elif lane == "SWING":
        ownership = "ACTIVE_SWING"
    else:
        ownership = "UNRESOLVED_FAIL_CLOSED"

    return {
        "schema_version": "astra_canonical_position_ownership_v1",
        "position_id": position_id,
        "symbol": symbol,
        "ownership": ownership,
        "lane": lane,
        "cohort": cohort_label,
        "active_strategy": ownership in {"ACTIVE_DAY", "ACTIVE_SWING", "ACTIVE_CRYPTO"},
        "legacy_quarantined": False,
        "broker_residue": False,
        "dust": False,
        "unresolved": ownership == "UNRESOLVED_FAIL_CLOSED",
        "included_in_total_exposure": True,
        "included_in_active_strategy": True,
        "included_in_legacy_quarantine": False,
        "reason": "lane_and_owner_resolved",
        "as_of": _iso(),
    }


_CANONICAL_LIFECYCLE_CLASSIFICATIONS = frozenset({
    "HOLD_AS_PLANNED",
    "HOLD_WITH_WATCH",
    "PROTECT_PROFIT",
    "EXIT_REVIEW",
    "CONTROLLED_LOSS_ACCEPTABLE",
    "THESIS_BROKEN",
    "REDUCE_RISK",
    "REPLACE_CANDIDATE",
    "DUST_CLEANUP_REVIEW",
    "INSUFFICIENT_EVIDENCE",
    "CONFLICTING_EVIDENCE",
    "LOW_CONFIDENCE",
})


# Priority order for merging conflicting classifications. Lower index = higher priority.
_CLASSIFICATION_PRIORITY = (
    "THESIS_BROKEN",
    "DUST_CLEANUP_REVIEW",
    "CONTROLLED_LOSS_ACCEPTABLE",
    "REPLACE_CANDIDATE",
    "PROTECT_PROFIT",
    "REDUCE_RISK",
    "EXIT_REVIEW",
    "HOLD_WITH_WATCH",
    "HOLD_AS_PLANNED",
    "CONFLICTING_EVIDENCE",
    "LOW_CONFIDENCE",
    "INSUFFICIENT_EVIDENCE",
)


def _classification_priority(state: str) -> int:
    try:
        return _CLASSIFICATION_PRIORITY.index(state)
    except ValueError:
        return len(_CLASSIFICATION_PRIORITY)


def _resolve_classification_conflicts(
    unified: dict[str, Any] | None,
    portfolio: dict[str, Any] | None,
    ownership: dict[str, Any],
) -> tuple[str, str, list[str]]:
    """Return the canonical classification, reason, and conflict notes."""
    u_state = _text((unified or {}).get("classification")).upper()
    p_state = _text((portfolio or {}).get("primary_state")).upper()
    if p_state == "KEEP":
        p_state = "HOLD_AS_PLANNED"
    if p_state == "DATA_INSUFFICIENT":
        p_state = "INSUFFICIENT_EVIDENCE"

    if not u_state and not p_state:
        return "INSUFFICIENT_EVIDENCE", "no_lifecycle_classification_source_available", []
    if not u_state:
        return p_state, "portfolio_classification_only", []
    if not p_state:
        return u_state, "unified_classification_only", []
    if u_state == p_state:
        return u_state, "unified_and_portfolio_agree", []

    # If ownership is quarantined, prefer unified because it is purpose-built for legacy.
    if ownership.get("legacy_quarantined"):
        if u_state:
            return u_state, "unified_preferred_for_legacy_quarantine", [f"portfolio_disagreement:{p_state}"] if p_state else []
        return p_state, "portfolio_fallback_for_legacy_quarantine", []

    # Otherwise use the higher-priority (more conservative) state.
    if _classification_priority(u_state) <= _classification_priority(p_state):
        return u_state, "unified_higher_priority", [f"portfolio_disagreement:{p_state}"]
    return p_state, "portfolio_higher_priority", [f"unified_disagreement:{u_state}"]


def resolve_canonical_lifecycle_decision_v1(
    position: Mapping[str, Any],
    *,
    unified_decision: Mapping[str, Any] | None = None,
    portfolio_review: Mapping[str, Any] | None = None,
    ownership: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve overlapping lifecycle recommendation sources into one canonical decision.

    The decision is advisory and non-executing. It includes the original
    component decisions as evidence but never produces more than one final
    classification per position.
    """
    row = dict(position or {})
    ownership = dict(ownership or {})
    if not ownership:
        ownership = resolve_canonical_position_ownership_v1(row)
    unified = dict(unified_decision or {})
    portfolio = dict(portfolio_review or {})

    classification, reason, conflicts = _resolve_classification_conflicts(unified, portfolio, ownership)
    position_id = _text(ownership.get("position_id") or row.get("position_id") or row.get("asset_id") or row.get("symbol"))
    symbol = _text(ownership.get("symbol") or row.get("symbol")).upper()
    lane = _text(ownership.get("lane") or row.get("lane_id")).upper()
    original_horizon = _text(
        row.get("original_horizon")
        or row.get("intended_horizon")
        or row.get("paper_entry_horizon_style")
        or row.get("trade_horizon_style")
        or unified.get("original_horizon")
    )
    provisional_horizon = _text(unified.get("provisional_horizon", {}).get("provisional_horizon") or unified.get("current_recommended_horizon"))
    confidence = _num(unified.get("forecast_confidence")) or _num(portfolio.get("confidence_score")) or 0.0
    exact_blocker = _text(unified.get("exact_blocker") or portfolio.get("exact_blocker"))
    if not exact_blocker:
        if classification in {"THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "REPLACE_CANDIDATE", "PROTECT_PROFIT", "REDUCE_RISK", "DUST_CLEANUP_REVIEW"}:
            exact_blocker = "LEGACY_CANARY_EXECUTION_DISABLED_BY_POLICY"
        else:
            exact_blocker = "ADVISORY_CLASSIFICATION_ONLY"

    return {
        "schema_version": "astra_canonical_lifecycle_decision_v1",
        "position_id": position_id,
        "symbol": symbol,
        "cohort": ownership.get("cohort"),
        "lane": lane,
        "ownership": ownership.get("ownership"),
        "original_horizon": original_horizon or "UNKNOWN",
        "provisional_horizon": provisional_horizon or "UNKNOWN",
        "classification": classification,
        "classification_reason": reason,
        "classification_confidence": round(confidence, 4),
        "evidence_conflicts": conflicts,
        "decision_owner": "astra_canonical_lifecycle_decision_v1",
        "decision_timestamp": _iso(now),
        "evidence_quality": unified.get("classification_components") or portfolio.get("evidence_quality"),
        "evidence_missing": list(unified.get("evidence_missing", []) or []),
        "evidence_stale": bool(unified.get("evidence_stale")),
        "execution_readiness": "NOT_READY" if ownership.get("unresolved") else "ADVISORY_REVIEW",
        "execution_authorized": False,
        "exact_blocker": exact_blocker,
        "paper_action_ready": False,
        "advisory_only": True,
        "source_decisions": {
            "unified_position_lifecycle": unified,
            "portfolio_capacity_review": portfolio,
        },
        "as_of": _iso(now),
    }


_PROPOSED_DISPOSITIONS = frozenset({
    "EXIT_NOW_REVIEW",
    "EXIT_NEXT_LIQUID_SESSION_REVIEW",
    "REDUCE_POSITION_REVIEW",
    "BOUNDED_RECOVERY_REVIEW",
    "HOLD_WITH_VERIFIED_THESIS",
    "DUST_CLOSE_REVIEW",
    "INSUFFICIENT_EVIDENCE_REVIEW",
})


def _map_classification_to_disposition(classification: str) -> str:
    mapping = {
        "THESIS_BROKEN": "EXIT_NOW_REVIEW",
        "CONTROLLED_LOSS_ACCEPTABLE": "EXIT_NOW_REVIEW",
        "PROTECT_PROFIT": "EXIT_NOW_REVIEW",
        "REDUCE_RISK": "REDUCE_POSITION_REVIEW",
        "REPLACE_CANDIDATE": "EXIT_NOW_REVIEW",
        "EXIT_REVIEW": "EXIT_NEXT_LIQUID_SESSION_REVIEW",
        "HOLD_WITH_WATCH": "BOUNDED_RECOVERY_REVIEW",
        "HOLD_AS_PLANNED": "HOLD_WITH_VERIFIED_THESIS",
        "DUST_CLEANUP_REVIEW": "DUST_CLOSE_REVIEW",
        "INSUFFICIENT_EVIDENCE": "INSUFFICIENT_EVIDENCE_REVIEW",
        "CONFLICTING_EVIDENCE": "INSUFFICIENT_EVIDENCE_REVIEW",
        "LOW_CONFIDENCE": "INSUFFICIENT_EVIDENCE_REVIEW",
    }
    return mapping.get(classification.upper(), "INSUFFICIENT_EVIDENCE_REVIEW")


def build_legacy_exit_readiness_v1(
    decision: Mapping[str, Any],
    *,
    position: Mapping[str, Any] | None = None,
    broker_position: Mapping[str, Any] | None = None,
    pending_map: Mapping[str, Any] | None = None,
    market_session: Mapping[str, Any] | None = None,
    asset_metadata: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Produce a broker-neutral exit-readiness contract for a legacy position.

    This is always advisory: execution_authorized remains False. No order is
    submitted.
    """
    d = dict(decision or {})
    pos = dict(position or {})
    broker = dict(broker_position or {})
    pending = dict(pending_map or {})
    symbol = _text(d.get("symbol") or pos.get("symbol")).upper()
    position_id = _text(d.get("position_id") or pos.get("position_id") or pos.get("asset_id"))
    classification = _text(d.get("classification")).upper()
    disposition = _map_classification_to_disposition(classification)
    broker_qty = _num(broker.get("qty") or broker.get("qty_available") or pos.get("qty") or pos.get("quantity"))
    position_qty = _num(pos.get("qty") or pos.get("quantity"))
    qty_reconciled = bool(broker_qty is not None and position_qty is not None and abs(broker_qty - position_qty) < 1e-6)
    pending_sell = any(
        _text(p.get("symbol")).upper() == symbol or _text(p.get("position_id")) == position_id
        for p in pending.values()
    )
    asset_meta = dict(asset_metadata or {})
    tradable = bool(asset_meta.get("tradable")) if "tradable" in asset_meta else (pos.get("tradable") is True)
    fractionable = bool(asset_meta.get("fractionable")) if "fractionable" in asset_meta else False
    session_ok = bool(market_session.get("market_is_tradable")) if market_session else None
    market_fresh = bool(d.get("evidence_stale") is False and d.get("evidence_missing") == [])
    duplicate_action = pending_sell

    blockers = []
    if not qty_reconciled:
        blockers.append("QUANTITY_NOT_RECONCILED")
    if pending_sell:
        blockers.append("DUPLICATE_PENDING_SELL")
    if not tradable:
        blockers.append("ASSET_NOT_TRADABLE")
    if market_session and session_ok is False:
        blockers.append("MARKET_SESSION_NOT_TRADABLE")
    if not market_fresh:
        blockers.append("MARKET_EVIDENCE_NOT_FRESH")
    # Canonical fail-closed policy blocker always present.
    blockers.append("LEGACY_CANARY_EXECUTION_DISABLED_BY_POLICY")

    return {
        "schema_version": "astra_legacy_exit_readiness_v1",
        "position_id": position_id,
        "symbol": symbol,
        "canonical_decision": d,
        "proposed_disposition": disposition,
        "broker_quantity_evidence_status": "RECONCILED" if qty_reconciled else "MISMATCH",
        "broker_quantity": broker_qty,
        "position_quantity": position_qty,
        "pending_sell": pending_sell,
        "asset_tradable": tradable,
        "asset_fractionable": fractionable,
        "market_session_tradable": session_ok,
        "market_evidence_fresh": market_fresh,
        "duplicate_action": duplicate_action,
        "reconciliation_status": "RECONCILED" if qty_reconciled else "PENDING_RECONCILIATION",
        "lifecycle_linkage_status": "LINKED" if bool(position_id) else "UNLINKED",
        "execution_blockers": blockers,
        "execution_authorized": False,
        "execution_ready": False,
        "as_of": _iso(now),
    }


def build_position_attribution_summary_v1(
    positions: Sequence[Mapping[str, Any]],
    *,
    broker_positions: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return separated canonical counts for total, active, legacy, dust exposure.

    Legacy positions remain included in totals. They are only excluded from
    active-strategy attribution.
    """
    broker_positions = dict(broker_positions or {})
    total_count = 0
    active_count = 0
    legacy_count = 0
    dust_count = 0
    broker_residue_count = 0
    unresolved_count = 0
    total_capital = 0.0
    active_capital = 0.0
    legacy_capital = 0.0
    dust_capital = 0.0
    total_unrealized_pnl = 0.0
    active_unrealized_pnl = 0.0
    legacy_unrealized_pnl = 0.0

    active_symbols: set[str] = set()
    legacy_symbols: set[str] = set()
    dust_symbols: set[str] = set()
    broker_residue_symbols: set[str] = set()
    unresolved_symbols: set[str] = set()

    for row in positions:
        if not isinstance(row, dict):
            continue
        ownership = resolve_canonical_position_ownership_v1(row)
        symbol = ownership.get("symbol", "")
        market_value = abs(_num(row.get("market_value")) or 0.0)
        cost_basis = abs(_num(row.get("cost_basis") or row.get("entry_price")) or 0.0) * abs(_num(row.get("qty") or row.get("quantity")) or 0.0)
        capital = market_value if market_value > 0 else cost_basis
        unrealized = _num(row.get("unrealized_pl") or row.get("unrealized_pnl")) or 0.0
        if unrealized == 0.0:
            unrealized_pct = _num(row.get("unrealized_plpc") or row.get("unrealized_return_pct")) or 0.0
            if abs(unrealized_pct) > 1e-9 and cost_basis > 0:
                unrealized = cost_basis * (unrealized_pct / 100.0)
            elif market_value > 0 and cost_basis > 0:
                unrealized = market_value - cost_basis

        total_count += 1
        total_capital += capital
        total_unrealized_pnl += unrealized

        ownership_state = ownership.get("ownership")
        if ownership_state == "LEGACY_QUARANTINED":
            legacy_count += 1
            legacy_capital += capital
            legacy_unrealized_pnl += unrealized
            legacy_symbols.add(symbol)
        elif ownership_state == "DUST_REVIEW":
            dust_count += 1
            dust_capital += capital
            dust_symbols.add(symbol)
        elif ownership_state == "BROKER_RESIDUE_REVIEW":
            broker_residue_count += 1
            broker_residue_symbols.add(symbol)
        elif ownership_state == "UNRESOLVED_FAIL_CLOSED":
            unresolved_count += 1
            unresolved_symbols.add(symbol)
        else:
            active_count += 1
            active_capital += capital
            active_unrealized_pnl += unrealized
            active_symbols.add(symbol)

    return {
        "schema_version": "astra_position_attribution_summary_v1",
        "as_of": _iso(now),
        "total_open_positions": total_count,
        "active_strategy_positions": active_count,
        "legacy_quarantined_positions": legacy_count,
        "dust_review_positions": dust_count,
        "broker_residue_review_positions": broker_residue_count,
        "unresolved_positions": unresolved_count,
        "total_committed_capital": round(total_capital, 4),
        "active_strategy_committed_capital": round(active_capital, 4),
        "legacy_committed_capital": round(legacy_capital, 4),
        "dust_committed_capital": round(dust_capital, 4),
        "total_unrealized_pnl": round(total_unrealized_pnl, 4),
        "active_strategy_unrealized_pnl": round(active_unrealized_pnl, 4),
        "legacy_unrealized_pnl": round(legacy_unrealized_pnl, 4),
        "active_strategy_symbols": sorted(active_symbols),
        "legacy_quarantined_symbols": sorted(legacy_symbols),
        "dust_review_symbols": sorted(dust_symbols),
        "broker_residue_symbols": sorted(broker_residue_symbols),
        "unresolved_symbols": sorted(unresolved_symbols),
        "broker_positions_considered": len(broker_positions),
    }


def ensure_fail_closed_canary_control_v1(
    control_path: str = "state/legacy_swing_canary_control_v1.json",
) -> dict[str, Any]:
    """Return the canonical fail-closed control state without activating it.

    If a control file exists and is already fail-closed, it is returned. If it
    is missing or malformed, the canonical disabled state is returned. This
    function does not write to the runtime state path; it only returns the
    value that the canonical persistence mechanism expects.
    """
    import json
    import os
    try:
        with open(control_path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return {
                "schema_version": "legacy_swing_canary_control_v1",
                "activation_state": _text(payload.get("activation_state"), "DISABLED_FAIL_CLOSED"),
                "enabled": bool(payload.get("enabled", False)),
                "kill_switch": bool(payload.get("kill_switch", True)),
                "readiness_state": _text(payload.get("readiness_state"), "NOT_READY"),
                "execution_authorized": False,
                "as_of": _iso(),
                "source": "existing_control_file",
            }
    except Exception:
        pass
    return {
        "schema_version": "legacy_swing_canary_control_v1",
        "activation_state": "DISABLED_FAIL_CLOSED",
        "enabled": False,
        "kill_switch": True,
        "readiness_state": "NOT_READY",
        "execution_authorized": False,
        "as_of": _iso(),
        "source": "absent_or_malformed_control_file",
    }


def bounded_legacy_quarantine_review_v1(
    positions: Sequence[Mapping[str, Any]],
    *,
    broker_positions: Mapping[str, Mapping[str, Any]] | None = None,
    pending_map: Mapping[str, Any] | None = None,
    market_session: Mapping[str, Any] | None = None,
    max_reviews: int = 1,
    prior_reviews: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run a bounded, worker-owned legacy review without executing exits.

    Produces readiness records and canonical attribution. Does not submit
    orders, refresh activation timestamps, or modify the canary control.
    """
    broker_positions = dict(broker_positions or {})
    pending_map = dict(pending_map or {})
    prior_reviews = dict(prior_reviews or {})
    reviewed: list[dict[str, Any]] = []
    activation_timestamps: dict[str, str] = {}

    for row in positions:
        if not isinstance(row, dict):
            continue
        ownership = resolve_canonical_position_ownership_v1(row)
        if ownership.get("ownership") != "LEGACY_QUARANTINED":
            continue
        if len(reviewed) >= max(1, int(max_reviews)):
            break
        symbol = ownership.get("symbol", "")
        position_id = ownership.get("position_id", "")
        # Preserve existing activation timestamp; never refresh it.
        activation_ts = _text(
            row.get("legacy_activation_timestamp")
            or row.get("forward_activation_timestamp")
            or prior_reviews.get(position_id, {}).get("activation_timestamp")
        )
        if not activation_ts:
            activation_ts = _iso(now)
        activation_timestamps[position_id] = activation_ts

        # Build canonical decision by reusing existing unified decision if present.
        unified = dict(row.get("unified_position_lifecycle_decision") or row.get("lifecycle_decision") or {})
        portfolio = dict(row.get("portfolio_capacity_review") or {})
        decision = resolve_canonical_lifecycle_decision_v1(
            row,
            unified_decision=unified,
            portfolio_review=portfolio,
            ownership=ownership,
            now=now,
        )
        broker = dict(broker_positions.get(symbol) or {})
        readiness = build_legacy_exit_readiness_v1(
            decision,
            position=row,
            broker_position=broker,
            pending_map=pending_map,
            market_session=market_session,
            now=now,
        )
        reviewed.append({
            "position_id": position_id,
            "symbol": symbol,
            "ownership": ownership,
            "activation_timestamp": activation_ts,
            "canonical_decision": decision,
            "exit_readiness": readiness,
            "reviewed_at": _iso(now),
        })

    return {
        "schema_version": "astra_bounded_legacy_quarantine_review_v1",
        "reviewed_count": len(reviewed),
        "max_reviews": max(1, int(max_reviews)),
        "reviewed": reviewed,
        "activation_timestamps": activation_timestamps,
        "execution_authorized": False,
        "canary_enabled": False,
        "kill_switch_active": True,
        "as_of": _iso(now),
    }
