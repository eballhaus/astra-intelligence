"""Canonical paper-only capacity accounting for evidence accumulation.

This module is deliberately side-effect free.  It accepts broker/account
snapshots produced by existing owners and returns one bounded decision model
for the allocator, PaperAutopilot, reports, Copilot, and Governance.  It never
queries a broker, changes configuration, or submits an order.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Mapping, Iterable


VERSION = "1.0.0"
LANES = ("SWING", "DAY", "SCALP", "CRYPTO")
APPROVED_CEILINGS = {"DAY": 15000.0, "SCALP": 15000.0, "CRYPTO": 10000.0}
APPROVED_CONCURRENT_POSITION_LIMITS = {"DAY": 3, "SCALP": 4, "CRYPTO": 4}
DEFAULT_GLOBAL_POSITION_LIMIT = 10
DEFAULT_BROKER_STATE_MAX_AGE_SECONDS = 120.0


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _age_seconds(value: Any, now: datetime | None = None) -> float | None:
    if value in (None, ""):
        return None
    try:
        text = _text(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        current = now or datetime.now(timezone.utc)
        return max(0.0, (current - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _lane_for_position(row: Mapping[str, Any]) -> str:
    lane = _text(row.get("lane_id") or row.get("position_owner")).upper()
    if lane in LANES:
        return lane
    asset = _text(row.get("asset_class") or row.get("asset_type")).lower()
    return "CRYPTO" if asset in {"crypto", "cryptocurrency"} else "SWING"


def _position_value(row: Mapping[str, Any]) -> float:
    for key in ("market_value", "position_value", "capital_occupied", "notional"):
        value = _number(row.get(key))
        if value is not None and value >= 0:
            return value
    qty = _number(row.get("qty") or row.get("quantity"))
    price = _number(row.get("current_price") or row.get("market_price"))
    return max(0.0, (qty or 0.0) * (price or 0.0)) if qty is not None and price is not None else 0.0


def _approved_legacy_slot_exclusion(row: Mapping[str, Any]) -> bool:
    """Allow a slot exclusion only for an explicitly approved legacy overlay.

    Broker exposure is never excluded.  This only distinguishes current
    strategy admission slots from legacy positions that remain fully included
    in portfolio-risk, buying-power, concentration, and reconciliation views.
    """
    return bool(
        _text(row.get("management_cohort")).upper() == "LEGACY_POSITION_RESOLUTION"
        and bool(row.get("decreasing_only"))
        and bool(row.get("legacy_migration_approved") or row.get("legacy_resolution_approved"))
        and bool(_text(row.get("legacy_migration_approval_id") or row.get("legacy_resolution_approval_id")))
        and bool(row.get("active_slot_exclusion") or row.get("active_slot_exclusion_approved"))
    )


def _strategy_capacity_excluded(row: Mapping[str, Any]) -> bool:
    """Return whether broker exposure must not occupy a strategy admission slot.

    Dust remains in the broker/global exposure denominator and reconciliation.
    This narrow exclusion only prevents an untradable residual from consuming a
    DAY or CRYPTO strategy reserve.
    """
    return bool(
        row.get("strategy_capacity_excluded")
        or row.get("is_dust")
        or _text(row.get("dust_state")).upper() == "BROKER_DUST_MONITORED"
    )


def _is_active_pending_order(row: Mapping[str, Any]) -> bool:
    """Return whether a broker order still occupies a reserve slot."""
    status = _text(row.get("status") or row.get("order_status")).lower()
    return status in {"new", "accepted", "pending_new", "accepted_for_bidding", "partially_filled", "pending_replace"}


def _is_active_commitment(row: Mapping[str, Any], now: datetime | None = None) -> bool:
    """Keep only short-lived worker commitments in the capacity contract."""
    state = _text(row.get("commitment_state") or row.get("state")).upper()
    if state not in {"REQUESTED", "HELD", "CONVERTED_TO_PENDING_ORDER"}:
        return False
    expires_at = _text(row.get("expires_at"))
    # _age_seconds is zero for future timestamps, so parse explicitly here.
    try:
        parsed = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc) > (now or datetime.now(timezone.utc))
    except (TypeError, ValueError):
        return False


def _reserve_config(lane: str, env: Mapping[str, Any]) -> dict[str, Any]:
    lane = _text(lane).upper()
    if lane == "DAY":
        enabled_key = "ASTRA_DAY_EVIDENCE_RESERVE_ENABLED"
        capital_key = "ASTRA_DAY_EVIDENCE_CAPITAL_LIMIT"
        position_key = "ASTRA_DAY_EVIDENCE_POSITION_LIMIT"
        entries_key = "ASTRA_DAY_EVIDENCE_MAX_DAILY_ENTRIES"
        loss_key = "ASTRA_DAY_EVIDENCE_MAX_DAILY_LOSS"
        fallback_capital_key = "ASTRA_DAY_LANE_CAPITAL_LIMIT"
    elif lane == "SCALP":
        # SCALP has its own bounded position count but consumes the existing
        # intraday capital book.  It must never create a second allocation.
        enabled_key = "ASTRA_DAY_EVIDENCE_RESERVE_ENABLED"
        capital_key = "ASTRA_DAY_EVIDENCE_CAPITAL_LIMIT"
        position_key = "ASTRA_SCALP_EVIDENCE_POSITION_LIMIT"
        entries_key = "ASTRA_SCALP_EVIDENCE_MAX_DAILY_ENTRIES"
        loss_key = "ASTRA_DAY_EVIDENCE_MAX_DAILY_LOSS"
        fallback_capital_key = "ASTRA_DAY_LANE_CAPITAL_LIMIT"
    elif lane == "CRYPTO":
        enabled_key = "ASTRA_CRYPTO_EVIDENCE_RESERVE_ENABLED"
        capital_key = "ASTRA_CRYPTO_EVIDENCE_CAPITAL_LIMIT"
        position_key = "ASTRA_CRYPTO_EVIDENCE_POSITION_LIMIT"
        entries_key = "ASTRA_CRYPTO_EVIDENCE_MAX_ROLLING_ENTRIES"
        loss_key = "ASTRA_CRYPTO_EVIDENCE_MAX_ROLLING_LOSS"
        fallback_capital_key = "ASTRA_CRYPTO_PAPER_CAPITAL_LIMIT"
    else:
        return {
            "lane_id": "SWING", "reserve_enabled": False, "reserve_type": "SWING_CORE",
            "capital_book_id": "paper_swing", "configured_capital_limit": None,
            "configured_position_limit": None, "max_entries": None, "max_loss": None,
            "capital_configuration_status": "CORE_BOOK",
        }
    raw_capital = env.get(capital_key)
    if raw_capital in (None, ""):
        raw_capital = env.get(fallback_capital_key)
    configured_capital = _number(raw_capital)
    ceiling = APPROVED_CEILINGS[lane]
    if configured_capital is None or configured_capital <= 0:
        capital_status = "CAPITAL_CONFIGURATION_REQUIRED" if raw_capital in (None, "") else "CAPITAL_CONFIGURATION_INVALID"
    elif configured_capital > ceiling:
        capital_status = "CAPITAL_LIMIT_EXCEEDS_APPROVAL"
    else:
        capital_status = "PASS"
    default_position_limit = env.get("ASTRA_PAPER_HORIZON_SCALP_CAPACITY", "4") if lane == "SCALP" else "1"
    raw_position_limit = env.get(position_key, default_position_limit)
    configured_position_limit = _integer(raw_position_limit, 1)
    if configured_position_limit <= 0:
        capital_status = "CAPITAL_CONFIGURATION_INVALID"
    elif configured_position_limit > APPROVED_CONCURRENT_POSITION_LIMITS[lane]:
        capital_status = "POSITION_LIMIT_EXCEEDS_APPROVAL"
    return {
        "lane_id": lane,
        "reserve_enabled": _truthy(env.get(enabled_key, "0")),
        "reserve_type": "EVIDENCE_RESERVE",
        "capital_book_id": "paper_day_learning" if lane in {"DAY", "SCALP"} else "paper_crypto_separate",
        "approved_ceiling": ceiling,
        "configured_capital_limit": configured_capital,
        "configured_position_limit": configured_position_limit,
        "approved_position_limit": APPROVED_CONCURRENT_POSITION_LIMITS[lane],
        "max_entries": max(0, _integer(env.get(entries_key, "2"), 2)),
        "max_loss": _number(env.get(loss_key)),
        "capital_configuration_status": capital_status,
        "environment_keys": {"enabled": enabled_key, "capital": capital_key, "position": position_key},
    }


def build_capacity_snapshot(
    *,
    broker_snapshot: Mapping[str, Any] | None = None,
    account_snapshot: Mapping[str, Any] | None = None,
    open_positions: Iterable[Mapping[str, Any]] | None = None,
    env: Mapping[str, Any] | None = None,
    global_position_limit: int | None = None,
    global_risk_allowed: bool = True,
    global_risk_reason: str = "",
    lane_entry_counts: Mapping[str, Any] | None = None,
    pending_orders: Iterable[Mapping[str, Any]] | None = None,
    active_commitments: Iterable[Mapping[str, Any]] | None = None,
    broker_state_max_age_seconds: float = DEFAULT_BROKER_STATE_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one fail-closed account and lane capacity snapshot."""
    values = env or os.environ
    # Historical entry attempts remain useful diagnostic telemetry, but never
    # consume an active reserve slot.  Current occupancy is broker positions,
    # broker pending orders, and bounded in-flight worker commitments only.
    entry_counts = {
        str(key).upper(): max(0, _integer(value, 0))
        for key, value in (lane_entry_counts or {}).items()
    }
    broker = dict(broker_snapshot or {})
    account = dict(account_snapshot or {})
    positions = [dict(row) for row in (open_positions or []) if isinstance(row, Mapping)]
    pending = [dict(row) for row in (pending_orders or []) if isinstance(row, Mapping) and _is_active_pending_order(row)]
    commitments = [dict(row) for row in (active_commitments or []) if isinstance(row, Mapping) and _is_active_commitment(row, now)]
    generated_at = _now_iso()
    state_age = _number(broker.get("broker_state_age_seconds"))
    if state_age is None:
        state_age = _age_seconds(broker.get("generated_at") or broker.get("timestamp"), now)
    fetch_ok = bool(broker.get("broker_positions_fetch_ok") or broker.get("positions_fetch_ok"))
    reconciliation_active = bool(broker.get("broker_reconciliation_active") or broker.get("reconciliation_active"))
    state_fresh = bool(fetch_ok and reconciliation_active and state_age is not None and state_age <= float(broker_state_max_age_seconds))
    if broker.get("broker_state_fresh") is True:
        state_fresh = True
    if broker.get("broker_state_stale") is True:
        state_fresh = False

    buying_power = _number(account.get("buying_power"))
    if buying_power is None:
        buying_power = _number(broker.get("buying_power"))
    equity = _number(account.get("equity"))
    cash = _number(account.get("cash"))
    distinct_symbols = {
        _text(row.get("symbol")).upper() for row in positions if _text(row.get("symbol"))
    }
    pending_symbols = {
        _text(row.get("symbol")).upper() for row in pending
        if _text(row.get("symbol")) and _text(row.get("symbol")).upper() not in distinct_symbols
    }
    commitment_symbols = {
        _text(row.get("symbol")).upper() for row in commitments
        if _text(row.get("symbol"))
        and _text(row.get("symbol")).upper() not in distinct_symbols
        and _text(row.get("symbol")).upper() not in pending_symbols
    }
    observed_count = _integer(broker.get("broker_open_positions_count"), -1)
    position_details_available = broker.get("position_details_available", True) is not False
    total_open = len(distinct_symbols) if position_details_available else (observed_count if observed_count >= 0 else None)
    global_limit = max(0, _integer(global_position_limit if global_position_limit is not None else values.get("ASTRA_PAPER_GLOBAL_POSITION_LIMIT", DEFAULT_GLOBAL_POSITION_LIMIT), DEFAULT_GLOBAL_POSITION_LIMIT))
    total_occupancy = (total_open + len(pending_symbols) + len(commitment_symbols)) if total_open is not None else None
    global_remaining = max(0, global_limit - total_occupancy) if state_fresh and total_occupancy is not None else None
    global_status = "AVAILABLE" if global_remaining and global_remaining > 0 else "GLOBAL_CAPACITY_EXHAUSTED"
    if not state_fresh:
        global_status = "BROKER_STATE_STALE"
    elif total_open is None:
        global_status = "BROKER_POSITION_DETAILS_UNAVAILABLE"
    excluded_legacy_symbols = {
        _text(row.get("symbol")).upper() for row in positions
        if _text(row.get("symbol")) and _approved_legacy_slot_exclusion(row)
    }
    excluded_dust_symbols = {
        _text(row.get("symbol")).upper() for row in positions
        if _text(row.get("symbol")) and _strategy_capacity_excluded(row)
    }
    legacy_exposure_symbols = {
        _text(row.get("symbol")).upper() for row in positions
        if _text(row.get("symbol")) and _text(row.get("management_cohort")).upper() == "LEGACY_POSITION_RESOLUTION"
    }
    active_strategy_open = len(distinct_symbols - excluded_legacy_symbols - excluded_dust_symbols) if position_details_available else None
    active_strategy_occupancy = (
        active_strategy_open + len(pending_symbols) + len(commitment_symbols)
        if active_strategy_open is not None else None
    )
    active_strategy_remaining = (
        max(0, global_limit - active_strategy_occupancy)
        if state_fresh and active_strategy_occupancy is not None else None
    )
    active_strategy_status = (
        "AVAILABLE" if active_strategy_remaining and active_strategy_remaining > 0
        else "ACTIVE_STRATEGY_SLOT_CAPACITY_EXHAUSTED"
    )
    if not state_fresh:
        active_strategy_status = "BROKER_STATE_STALE"
    elif active_strategy_open is None:
        active_strategy_status = "BROKER_POSITION_DETAILS_UNAVAILABLE"
    lane_rows: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    lane_pending: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    lane_commitments: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    for row in positions:
        lane_rows[_lane_for_position(row)].append(row)
    for row in pending:
        lane_pending[_lane_for_position(row)].append(row)
    for row in commitments:
        lane = _text(row.get("lane_id")).upper()
        if lane in lane_commitments:
            lane_commitments[lane].append(row)

    lanes: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        config = _reserve_config(lane, values)
        raw_lane_rows = lane_rows[lane]
        active_lane_rows = [
            row for row in raw_lane_rows
            if not _approved_legacy_slot_exclusion(row) and not _strategy_capacity_excluded(row)
        ]
        legacy_excluded_rows = [row for row in raw_lane_rows if _approved_legacy_slot_exclusion(row)]
        dust_excluded_rows = [row for row in raw_lane_rows if _strategy_capacity_excluded(row)]
        open_position_count = len(active_lane_rows)
        pending_order_count = len(lane_pending[lane])
        active_commitment_count = len(lane_commitments[lane])
        used = open_position_count + pending_order_count + active_commitment_count
        if lane in {"DAY", "SCALP"}:
            # Both intraday execution lanes use one approved capital book.
            # Per-lane position limits remain separate; capital accounting is
            # deliberately shared to prevent concurrent double allocation.
            shared_rows = [
                row
                for intraday_lane in ("DAY", "SCALP")
                for row in lane_rows[intraday_lane]
                if not _approved_legacy_slot_exclusion(row) and not _strategy_capacity_excluded(row)
            ]
            shared_pending = [row for intraday_lane in ("DAY", "SCALP") for row in lane_pending[intraday_lane]]
            used_capital = round(sum(_position_value(row) for row in shared_rows + shared_pending), 4)
        else:
            used_capital = round(sum(_position_value(row) for row in active_lane_rows + lane_pending[lane]), 4)
        legacy_excluded_capital = round(sum(_position_value(row) for row in legacy_excluded_rows), 4)
        dust_excluded_capital = round(sum(_position_value(row) for row in dust_excluded_rows), 4)
        raw_lane_capital = round(used_capital + legacy_excluded_capital + dust_excluded_capital, 4)
        configured_limit = config.get("configured_capital_limit")
        capital_remaining = round(max(0.0, configured_limit - used_capital), 4) if configured_limit is not None else None
        position_limit = config.get("configured_position_limit")
        positions_remaining = max(0, int(position_limit) - used) if position_limit is not None else None
        max_entries = config.get("max_entries")
        historical_entries_used = entry_counts.get(lane, 0)
        historical_entries_remaining = max(0, int(max_entries) - historical_entries_used) if max_entries is not None else None
        blockers: list[str] = []
        if not state_fresh:
            blockers.append("BROKER_STATE_STALE")
        elif not position_details_available and lane in {"DAY", "SCALP", "CRYPTO"}:
            blockers.append("BROKER_POSITION_DETAILS_UNAVAILABLE")
        if lane in {"DAY", "SCALP", "CRYPTO"}:
            if config.get("capital_configuration_status") != "PASS":
                blockers.append(str(config.get("capital_configuration_status")))
            if not config.get("reserve_enabled"):
                blockers.append("CAPITAL_NOT_CONFIGURED")
            if positions_remaining is not None and positions_remaining <= 0:
                blockers.append("LANE_POSITION_LIMIT_REACHED")
            if capital_remaining is not None and capital_remaining <= 0:
                blockers.append("LANE_RESERVE_EXHAUSTED")
        if buying_power is None:
            blockers.append("BUYING_POWER_UNAVAILABLE")
        elif buying_power <= 0:
            blockers.append("BUYING_POWER_INSUFFICIENT")
        if not global_risk_allowed:
            blockers.append(_text(global_risk_reason) or "GLOBAL_RISK_BLOCKED")
        reserve_available = not blockers
        if lane == "SWING":
            slot_available = active_strategy_remaining is not None and active_strategy_remaining > 0
            # SWING capacity is the approved active-slot authority.  Entry
            # velocity is separately bounded by PaperAutopilot per-cycle gates.
            decision = "AVAILABLE" if reserve_available and slot_available else (
                "ACTIVE_STRATEGY_SLOT_CAPACITY_EXHAUSTED" if state_fresh else "BROKER_STATE_STALE"
            )
        else:
            if not reserve_available:
                if "GLOBAL_RISK_BLOCKED" in blockers:
                    decision = "GLOBAL_RISK_BLOCKED"
                elif "BROKER_STATE_STALE" in blockers:
                    decision = "BROKER_STATE_STALE"
                elif any(item in blockers for item in ("LANE_POSITION_LIMIT_REACHED", "LANE_RESERVE_EXHAUSTED")):
                    decision = "LANE_RESERVE_EXHAUSTED"
                elif any(item in blockers for item in ("CAPITAL_CONFIGURATION_REQUIRED", "CAPITAL_CONFIGURATION_INVALID", "CAPITAL_NOT_CONFIGURED")):
                    decision = "CAPITAL_NOT_CONFIGURED"
                elif "BUYING_POWER_INSUFFICIENT" in blockers:
                    decision = "BUYING_POWER_INSUFFICIENT"
                else:
                    decision = "FAIL_CLOSED"
            else:
                decision = "AVAILABLE_FROM_LANE_RESERVE" if not global_remaining else "AVAILABLE"
        if lane in {"DAY", "SCALP", "CRYPTO"} and state_fresh:
            if active_commitment_count > 0:
                reserve_state = "RESERVED_FOR_IN_FLIGHT_CANDIDATE"
            elif pending_order_count > 0:
                reserve_state = "PENDING_ORDER_CONSUMES_RESERVE"
            elif open_position_count > 0:
                reserve_state = "OPEN_POSITION_CONSUMES_RESERVE"
            else:
                reserve_state = decision
        else:
            reserve_state = decision
        lanes[lane.lower()] = {
            "lane_id": lane,
            "lane_enabled": _truthy(values.get("ASTRA_DAY_LANE_PILOT_ENABLED", "0")) if lane in {"DAY", "SCALP"} else _truthy(values.get("ASTRA_ENABLE_ALPACA_CRYPTO_PAPER", "0")) if lane == "CRYPTO" else True,
            "execution_enabled": True if lane == "SWING" else bool(config.get("reserve_enabled")),
            "capital_book_id": config.get("capital_book_id"),
            "reserve_enabled": bool(config.get("reserve_enabled")),
            "reserve_type": config.get("reserve_type"),
            "configured_capital_limit": configured_limit,
            "effective_capital_limit": configured_limit,
            "approved_ceiling": config.get("approved_ceiling"),
            "capital_used": used_capital,
            "raw_broker_capital_used": raw_lane_capital,
            "legacy_excluded_capital": legacy_excluded_capital,
            "capital_remaining": capital_remaining,
            "configured_position_limit": position_limit,
            "approved_position_limit": config.get("approved_position_limit"),
            "positions_used": used,
            "raw_broker_position_count": len(raw_lane_rows),
            "legacy_excluded_position_count": len(legacy_excluded_rows),
            "dust_strategy_slot_exclusion_count": len(dust_excluded_rows),
            "dust_strategy_slot_exclusion_capital": dust_excluded_capital,
            "positions_remaining": positions_remaining,
            "open_position_count": open_position_count,
            "pending_order_count": pending_order_count,
            "active_commitment_count": active_commitment_count,
            "current_reserve_occupancy_count": used,
            "reserve_available": bool(reserve_available and (lane != "SWING" or decision == "AVAILABLE")),
            "reserve_state": reserve_state,
            "broker_buying_power_sufficient": buying_power is not None and buying_power > 0,
            "global_account_risk_allowed": bool(global_risk_allowed),
            "lane_risk_allowed": bool(state_fresh),
            # Candidate admission separately enforces this same invariant;
            # capacity telemetry must not advertise a contradictory policy.
            "duplicate_exposure_allowed": False,
            "capacity_decision": decision,
            "exact_blockers": list(dict.fromkeys(blockers)),
            # Only the worker may refresh this snapshot.  Readers can inspect
            # it, but a stale read can never authorize a new position.
            "capacity_authority_owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
            "capacity_authority_timestamp": generated_at,
            "capacity_authority_state": "CURRENT" if state_fresh else "BROKER_UNREACHABLE" if not fetch_ok else "STALE",
            "max_entries": config.get("max_entries"),
            "entries_used": historical_entries_used,
            "entries_remaining": historical_entries_remaining,
            "historical_entries_used": historical_entries_used,
            "historical_entries_remaining": historical_entries_remaining,
            "historical_entry_counts_advisory_only": True,
            "max_loss": config.get("max_loss"),
        }
    snapshot_basis = "|".join([
        generated_at, str(total_occupancy), str(global_limit), str(buying_power),
        str(active_strategy_occupancy), str(len(excluded_legacy_symbols)),
        str(lanes.get("day", {}).get("capacity_decision")), str(lanes.get("crypto", {}).get("capacity_decision")),
    ])
    snapshot_id = hashlib.sha256(snapshot_basis.encode("utf-8")).hexdigest()[:20]
    result = {
        "capacity_contract": "astra_evidence_accumulation_capacity_v1",
        "version": VERSION,
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "paper_mode_verified": True,
        "broker_reconciliation_status": "FRESH" if state_fresh else "STALE_OR_UNAVAILABLE",
        "capacity_authority_owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
        "capacity_authority_timestamp": generated_at,
        "capacity_authority_state": "CURRENT" if state_fresh else "BROKER_UNREACHABLE" if not fetch_ok else "STALE",
        "broker_state_age_seconds": round(state_age, 3) if state_age is not None else None,
        "broker_state_max_age_seconds": float(broker_state_max_age_seconds),
        "account_equity": equity,
        "buying_power": buying_power,
        "cash": cash,
        "total_open_positions": total_open if state_fresh else None,
        "global_current_occupancy": total_occupancy if state_fresh else None,
        "broker_total_exposure_position_count": total_open if state_fresh else None,
        "legacy_existing_exposure_position_count": len(legacy_exposure_symbols) if state_fresh else None,
        "current_managed_exposure_position_count": (len(distinct_symbols - legacy_exposure_symbols) if state_fresh else None),
        "total_account_risk_capacity": {
            "state": "CURRENT" if state_fresh and global_risk_allowed else "BLOCKED",
            "broker_total_positions_included": total_open if state_fresh else None,
            "approved_legacy_slot_exclusions_remain_risk_included": True,
            "global_risk_allowed": bool(global_risk_allowed),
        },
        "active_strategy_slot_occupancy": active_strategy_occupancy if state_fresh else None,
        "active_strategy_slot_capacity_remaining": active_strategy_remaining,
        "active_strategy_slot_capacity_status": active_strategy_status,
        "approved_legacy_slot_exclusion_symbols": sorted(excluded_legacy_symbols),
        "approved_legacy_slot_exclusion_count": len(excluded_legacy_symbols),
        "total_open_orders": _number(account.get("open_orders_count")),
        "pending_order_count": len(pending),
        "active_commitment_count": len(commitments),
        "global_position_limit": global_limit,
        "global_capacity_remaining": global_remaining,
        "global_capacity_status": global_status,
        "global_risk_allowed": bool(global_risk_allowed),
        "global_risk_reason": _text(global_risk_reason),
        "swing_core_capital_used": lanes["swing"]["capital_used"],
        "swing_core_position_count": lanes["swing"]["positions_used"],
        "swing_core_capacity_remaining": active_strategy_remaining if excluded_legacy_symbols else global_remaining,
        "swing_capacity_authority": "ACTIVE_STRATEGY_SLOT_CAPACITY",
        "swing_entry_velocity_owner": "PaperAutopilot.max_new_positions_per_cycle",
        "reserve_capital_excluded_from_swing": True,
        "lane_entry_counts": entry_counts,
        "historical_entry_counts_advisory_only": True,
        "lanes": lanes,
        "optional_general_evidence_reserve": {"status": "GENERAL_EVIDENCE_RESERVE_NOT_REQUIRED", "enabled": False},
        "stale_state_cannot_authorize_capacity": True,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }
    for lane in ("day", "crypto"):
        prefix = lane
        view = lanes[lane]
        result[f"{prefix}_open_positions"] = view["open_position_count"]
        result[f"{prefix}_pending_orders"] = view["pending_order_count"]
        result[f"{prefix}_active_commitments"] = view["active_commitment_count"]
        result[f"{prefix}_positions_used"] = view["positions_used"]
        result[f"{prefix}_positions_remaining"] = view["positions_remaining"]
        result[f"{prefix}_reserve_available"] = view["reserve_available"]
        result[f"{prefix}_reserve_state"] = view["reserve_state"]
    return result


def candidate_capacity_decision(
    snapshot: Mapping[str, Any],
    *,
    lane_id: str,
    symbol: str = "",
    open_symbols: Iterable[str] | None = None,
    global_risk_allowed: bool | None = None,
) -> dict[str, Any]:
    lane = _text(lane_id).upper()
    payload = dict((snapshot.get("lanes") or {}).get(lane.lower()) or {})
    blockers = list(payload.get("exact_blockers") or [])
    if _text(symbol).upper() in {_text(item).upper() for item in (open_symbols or []) if _text(item)}:
        blockers.append("DUPLICATE_EXPOSURE_BLOCKED")
    if global_risk_allowed is False:
        blockers.append("GLOBAL_RISK_BLOCKED")
    if snapshot.get("broker_reconciliation_status") != "FRESH":
        blockers.append("BROKER_STATE_STALE")
    # Dust and Governance-approved legacy overlays remain in the broker-wide
    # risk denominator, but the snapshot already excludes them from strategy
    # admission slots.  SWING must use that same established slot authority
    # rather than fail on the raw broker count alone.
    dust_slot_exclusions = sum(
        _integer(view.get("dust_strategy_slot_exclusion_count"), 0)
        for view in (snapshot.get("lanes") or {}).values()
        if isinstance(view, Mapping)
    )
    strategy_slot_exclusions = (
        _integer(snapshot.get("approved_legacy_slot_exclusion_count"), 0)
        + dust_slot_exclusions
    )
    swing_uses_active_strategy_slots = lane == "SWING" and strategy_slot_exclusions > 0
    if lane == "SWING" and _integer(snapshot.get("global_capacity_remaining"), 0) <= 0:
        if swing_uses_active_strategy_slots:
            if _integer(snapshot.get("active_strategy_slot_capacity_remaining"), 0) <= 0:
                blockers.append("ACTIVE_STRATEGY_SLOT_CAPACITY_EXHAUSTED")
        else:
            blockers.append("GLOBAL_CAPACITY_EXHAUSTED")
    decision = payload.get("capacity_decision") or "FAIL_CLOSED"
    # When an approved legacy overlay or broker dust is excluded from strategy
    # slots, current-strategy admission uses the dedicated slot view. Total
    # account-risk and buying-power checks still apply to every broker row.
    if (
        swing_uses_active_strategy_slots
        and _integer(snapshot.get("active_strategy_slot_capacity_remaining"), 0) > 0
        and snapshot.get("broker_reconciliation_status") == "FRESH"
        and not blockers
    ):
        decision = "AVAILABLE"
    if blockers:
        if "DUPLICATE_EXPOSURE_BLOCKED" in blockers:
            decision = "DUPLICATE_EXPOSURE_BLOCKED"
        elif "GLOBAL_RISK_BLOCKED" in blockers:
            decision = "GLOBAL_RISK_BLOCKED"
        elif "BROKER_STATE_STALE" in blockers:
            decision = "BROKER_STATE_STALE"
        elif lane == "SWING" and "GLOBAL_CAPACITY_EXHAUSTED" in blockers:
            decision = "GLOBAL_CAPACITY_EXHAUSTED"
        elif lane == "SWING" and "ACTIVE_STRATEGY_SLOT_CAPACITY_EXHAUSTED" in blockers:
            decision = "ACTIVE_STRATEGY_SLOT_CAPACITY_EXHAUSTED"
        elif any(item in blockers for item in ("LANE_POSITION_LIMIT_REACHED", "LANE_RESERVE_EXHAUSTED")):
            decision = "LANE_RESERVE_EXHAUSTED"
        else:
            decision = "FAIL_CLOSED"
    return {
        "capacity_decision": decision,
        "capacity_source": "astra_evidence_accumulation_capacity_v1",
        "snapshot_id": snapshot.get("snapshot_id"),
        "global_capacity_status": snapshot.get("global_capacity_status"),
        "active_strategy_slot_capacity_status": snapshot.get("active_strategy_slot_capacity_status"),
        "active_strategy_slot_capacity_remaining": snapshot.get("active_strategy_slot_capacity_remaining"),
        "approved_legacy_slot_exclusion_count": snapshot.get("approved_legacy_slot_exclusion_count", 0),
        "dust_strategy_slot_exclusion_count": dust_slot_exclusions,
        "strategy_slot_exclusion_count": strategy_slot_exclusions,
        "lane_reserve_status": payload.get("capacity_decision"),
        "reserve_enabled": bool(payload.get("reserve_enabled", False)),
        "reserve_available": bool(payload.get("reserve_available", False)),
        "reserve_state": payload.get("reserve_state"),
        "capital_remaining": payload.get("capital_remaining"),
        "capital_used": payload.get("capital_used"),
        "configured_capital_limit": payload.get("configured_capital_limit"),
        "positions_remaining": payload.get("positions_remaining"),
        "positions_used": payload.get("positions_used"),
        "configured_position_limit": payload.get("configured_position_limit"),
        "open_position_count": payload.get("open_position_count", 0),
        "pending_order_count": payload.get("pending_order_count", 0),
        "active_commitment_count": payload.get("active_commitment_count", 0),
        "exact_blockers": list(dict.fromkeys(blockers)),
        "allowed": decision in {"AVAILABLE", "AVAILABLE_FROM_LANE_RESERVE"},
    }


def canonical_candidate_capacity_fact(
    snapshot: Mapping[str, Any] | None,
    *,
    lane_id: str,
    symbol: str = "",
    open_symbols: Iterable[str] | None = None,
    global_risk_allowed: bool | None = None,
) -> dict[str, Any]:
    """Return the only capacity fact a candidate execution consumer may use.

    The existing capacity decision remains the policy owner.  This thin
    envelope adds provenance and freshness so a consumer cannot accidentally
    substitute a legacy boolean such as ``day_trade_capacity_available``.
    It is pure and fail-closed when the worker-owned broker snapshot is absent
    or not fresh.
    """
    source = dict(snapshot or {})
    lane = _text(lane_id).upper()
    decision = candidate_capacity_decision(
        source,
        lane_id=lane,
        symbol=symbol,
        open_symbols=open_symbols,
        global_risk_allowed=global_risk_allowed,
    ) if source else {
        "capacity_decision": "BROKER_STATE_STALE",
        "exact_blockers": ["CANONICAL_CAPACITY_SNAPSHOT_MISSING"],
        "allowed": False,
    }
    fresh = bool(source) and _text(source.get("broker_reconciliation_status")).upper() == "FRESH"
    authority_current = bool(fresh and source.get("snapshot_id"))
    exact_blockers = list(decision.get("exact_blockers") or [])
    if not authority_current:
        exact_blockers.append("CANONICAL_CAPACITY_AUTHORITY_NOT_CURRENT")
    return {
        **decision,
        "fact_id": "CANONICAL_CANDIDATE_CAPACITY_FACT",
        "lane_id": lane,
        "symbol": _text(symbol).upper() or None,
        "authority_owner": "astra_evidence_accumulation_capacity_v1.build_capacity_snapshot",
        "authority_snapshot_id": source.get("snapshot_id"),
        "authority_generated_at": source.get("generated_at"),
        "authority_reconciliation_status": source.get("broker_reconciliation_status"),
        "authority_current": authority_current,
        "exact_blockers": list(dict.fromkeys(exact_blockers)),
        "allowed": bool(decision.get("allowed")) and authority_current,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }
