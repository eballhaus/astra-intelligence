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
LANES = ("SWING", "DAY", "CRYPTO")
APPROVED_CEILINGS = {"DAY": 15000.0, "CRYPTO": 10000.0}
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


def _reserve_config(lane: str, env: Mapping[str, Any]) -> dict[str, Any]:
    lane = _text(lane).upper()
    if lane == "DAY":
        enabled_key = "ASTRA_DAY_EVIDENCE_RESERVE_ENABLED"
        capital_key = "ASTRA_DAY_EVIDENCE_CAPITAL_LIMIT"
        position_key = "ASTRA_DAY_EVIDENCE_POSITION_LIMIT"
        entries_key = "ASTRA_DAY_EVIDENCE_MAX_DAILY_ENTRIES"
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
    raw_position_limit = env.get(position_key, "1")
    configured_position_limit = _integer(raw_position_limit, 1)
    if configured_position_limit <= 0:
        capital_status = "CAPITAL_CONFIGURATION_INVALID"
    return {
        "lane_id": lane,
        "reserve_enabled": _truthy(env.get(enabled_key, "0")),
        "reserve_type": "EVIDENCE_RESERVE",
        "capital_book_id": "paper_day_learning" if lane == "DAY" else "paper_crypto_separate",
        "approved_ceiling": ceiling,
        "configured_capital_limit": configured_capital,
        "configured_position_limit": configured_position_limit,
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
    broker_state_max_age_seconds: float = DEFAULT_BROKER_STATE_MAX_AGE_SECONDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one fail-closed account and lane capacity snapshot."""
    values = env or os.environ
    entry_counts = {
        str(key).upper(): max(0, _integer(value, 0))
        for key, value in (lane_entry_counts or {}).items()
    }
    broker = dict(broker_snapshot or {})
    account = dict(account_snapshot or {})
    positions = [dict(row) for row in (open_positions or []) if isinstance(row, Mapping)]
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
    observed_count = _integer(broker.get("broker_open_positions_count"), -1)
    position_details_available = broker.get("position_details_available", True) is not False
    total_open = len(distinct_symbols) if position_details_available else (observed_count if observed_count >= 0 else None)
    global_limit = max(0, _integer(global_position_limit if global_position_limit is not None else values.get("ASTRA_PAPER_GLOBAL_POSITION_LIMIT", DEFAULT_GLOBAL_POSITION_LIMIT), DEFAULT_GLOBAL_POSITION_LIMIT))
    global_remaining = max(0, global_limit - total_open) if state_fresh and total_open is not None else None
    global_status = "AVAILABLE" if global_remaining and global_remaining > 0 else "GLOBAL_CAPACITY_EXHAUSTED"
    if not state_fresh:
        global_status = "BROKER_STATE_STALE"
    elif total_open is None:
        global_status = "BROKER_POSITION_DETAILS_UNAVAILABLE"
    lane_rows: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANES}
    for row in positions:
        lane_rows[_lane_for_position(row)].append(row)

    lanes: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        config = _reserve_config(lane, values)
        used = len(lane_rows[lane])
        used_capital = round(sum(_position_value(row) for row in lane_rows[lane]), 4)
        configured_limit = config.get("configured_capital_limit")
        capital_remaining = round(max(0.0, configured_limit - used_capital), 4) if configured_limit is not None else None
        position_limit = config.get("configured_position_limit")
        positions_remaining = max(0, int(position_limit) - used) if position_limit is not None else None
        max_entries = config.get("max_entries")
        entries_used = entry_counts.get(lane, 0)
        entries_remaining = max(0, int(max_entries) - entries_used) if max_entries is not None else None
        blockers: list[str] = []
        if not state_fresh:
            blockers.append("BROKER_STATE_STALE")
        elif not position_details_available and lane in {"DAY", "CRYPTO"}:
            blockers.append("BROKER_POSITION_DETAILS_UNAVAILABLE")
        if lane in {"DAY", "CRYPTO"}:
            if config.get("capital_configuration_status") != "PASS":
                blockers.append(str(config.get("capital_configuration_status")))
            if not config.get("reserve_enabled"):
                blockers.append("CAPITAL_NOT_CONFIGURED")
            if positions_remaining is not None and positions_remaining <= 0:
                blockers.append("LANE_POSITION_LIMIT_REACHED")
            if capital_remaining is not None and capital_remaining <= 0:
                blockers.append("LANE_RESERVE_EXHAUSTED")
            if entries_remaining is not None and entries_remaining <= 0:
                blockers.append("LANE_ENTRY_LIMIT_REACHED")
        if buying_power is None:
            blockers.append("BUYING_POWER_UNAVAILABLE")
        elif buying_power <= 0:
            blockers.append("BUYING_POWER_INSUFFICIENT")
        if not global_risk_allowed:
            blockers.append(_text(global_risk_reason) or "GLOBAL_RISK_BLOCKED")
        reserve_available = not blockers
        if lane == "SWING":
            decision = "AVAILABLE" if reserve_available and global_remaining and global_remaining > 0 else ("GLOBAL_CAPACITY_EXHAUSTED" if state_fresh else "BROKER_STATE_STALE")
            if global_remaining == 0 and reserve_available:
                decision = "GLOBAL_CAPACITY_EXHAUSTED"
        else:
            if not reserve_available:
                if "GLOBAL_RISK_BLOCKED" in blockers:
                    decision = "GLOBAL_RISK_BLOCKED"
                elif "BROKER_STATE_STALE" in blockers:
                    decision = "BROKER_STATE_STALE"
                elif any(item in blockers for item in ("LANE_POSITION_LIMIT_REACHED", "LANE_RESERVE_EXHAUSTED", "LANE_ENTRY_LIMIT_REACHED")):
                    decision = "LANE_RESERVE_EXHAUSTED"
                elif any(item in blockers for item in ("CAPITAL_CONFIGURATION_REQUIRED", "CAPITAL_CONFIGURATION_INVALID", "CAPITAL_NOT_CONFIGURED")):
                    decision = "CAPITAL_NOT_CONFIGURED"
                elif "BUYING_POWER_INSUFFICIENT" in blockers:
                    decision = "BUYING_POWER_INSUFFICIENT"
                else:
                    decision = "FAIL_CLOSED"
            else:
                decision = "AVAILABLE_FROM_LANE_RESERVE" if not global_remaining else "AVAILABLE"
        lanes[lane.lower()] = {
            "lane_id": lane,
            "lane_enabled": _truthy(values.get("ASTRA_DAY_LANE_PILOT_ENABLED", "0")) if lane == "DAY" else _truthy(values.get("ASTRA_ENABLE_ALPACA_CRYPTO_PAPER", "0")) if lane == "CRYPTO" else True,
            "execution_enabled": True if lane == "SWING" else bool(config.get("reserve_enabled")),
            "capital_book_id": config.get("capital_book_id"),
            "reserve_enabled": bool(config.get("reserve_enabled")),
            "reserve_type": config.get("reserve_type"),
            "configured_capital_limit": configured_limit,
            "effective_capital_limit": configured_limit,
            "approved_ceiling": config.get("approved_ceiling"),
            "capital_used": used_capital,
            "capital_remaining": capital_remaining,
            "configured_position_limit": position_limit,
            "positions_used": used,
            "positions_remaining": positions_remaining,
            "reserve_available": bool(reserve_available and lane != "SWING"),
            "broker_buying_power_sufficient": buying_power is not None and buying_power > 0,
            "global_account_risk_allowed": bool(global_risk_allowed),
            "lane_risk_allowed": bool(state_fresh),
            "duplicate_exposure_allowed": True,
            "capacity_decision": decision,
            "exact_blockers": list(dict.fromkeys(blockers)),
            "max_entries": config.get("max_entries"),
            "entries_used": entries_used,
            "entries_remaining": entries_remaining,
            "max_loss": config.get("max_loss"),
        }
    snapshot_basis = "|".join([
        generated_at, str(total_open), str(global_limit), str(buying_power),
        str(lanes.get("day", {}).get("capacity_decision")), str(lanes.get("crypto", {}).get("capacity_decision")),
    ])
    snapshot_id = hashlib.sha256(snapshot_basis.encode("utf-8")).hexdigest()[:20]
    return {
        "capacity_contract": "astra_evidence_accumulation_capacity_v1",
        "version": VERSION,
        "generated_at": generated_at,
        "snapshot_id": snapshot_id,
        "paper_mode_verified": True,
        "broker_reconciliation_status": "FRESH" if state_fresh else "STALE_OR_UNAVAILABLE",
        "broker_state_age_seconds": round(state_age, 3) if state_age is not None else None,
        "broker_state_max_age_seconds": float(broker_state_max_age_seconds),
        "account_equity": equity,
        "buying_power": buying_power,
        "cash": cash,
        "total_open_positions": total_open if state_fresh else None,
        "total_open_orders": _number(account.get("open_orders_count")),
        "global_position_limit": global_limit,
        "global_capacity_remaining": global_remaining,
        "global_capacity_status": global_status,
        "global_risk_allowed": bool(global_risk_allowed),
        "global_risk_reason": _text(global_risk_reason),
        "swing_core_capital_used": lanes["swing"]["capital_used"],
        "swing_core_position_count": lanes["swing"]["positions_used"],
        "swing_core_capacity_remaining": global_remaining,
        "reserve_capital_excluded_from_swing": True,
        "lane_entry_counts": entry_counts,
        "lanes": lanes,
        "optional_general_evidence_reserve": {"status": "GENERAL_EVIDENCE_RESERVE_NOT_REQUIRED", "enabled": False},
        "stale_state_cannot_authorize_capacity": True,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }


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
    if lane == "SWING" and _integer(snapshot.get("global_capacity_remaining"), 0) <= 0:
        blockers.append("GLOBAL_CAPACITY_EXHAUSTED")
    decision = payload.get("capacity_decision") or "FAIL_CLOSED"
    if blockers:
        if "DUPLICATE_EXPOSURE_BLOCKED" in blockers:
            decision = "DUPLICATE_EXPOSURE_BLOCKED"
        elif "GLOBAL_RISK_BLOCKED" in blockers:
            decision = "GLOBAL_RISK_BLOCKED"
        elif "BROKER_STATE_STALE" in blockers:
            decision = "BROKER_STATE_STALE"
        elif lane == "SWING" and "GLOBAL_CAPACITY_EXHAUSTED" in blockers:
            decision = "GLOBAL_CAPACITY_EXHAUSTED"
        elif any(item in blockers for item in ("LANE_POSITION_LIMIT_REACHED", "LANE_RESERVE_EXHAUSTED", "LANE_ENTRY_LIMIT_REACHED")):
            decision = "LANE_RESERVE_EXHAUSTED"
        else:
            decision = "FAIL_CLOSED"
    return {
        "capacity_decision": decision,
        "capacity_source": "astra_evidence_accumulation_capacity_v1",
        "snapshot_id": snapshot.get("snapshot_id"),
        "global_capacity_status": snapshot.get("global_capacity_status"),
        "lane_reserve_status": payload.get("capacity_decision"),
        "capital_remaining": payload.get("capital_remaining"),
        "positions_remaining": payload.get("positions_remaining"),
        "exact_blockers": list(dict.fromkeys(blockers)),
        "allowed": decision in {"AVAILABLE", "AVAILABLE_FROM_LANE_RESERVE"},
    }
