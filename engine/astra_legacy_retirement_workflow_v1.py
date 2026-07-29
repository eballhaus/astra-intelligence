"""Non-executing legacy position retirement review queue.

This module produces an advisory review queue for positions whose reset scope is
``LEGACY_PRE_RESET_POSITION`` or ``DUST``.  It never submits broker orders,
changes sell protections, or alters central execution.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from engine.astra_canonical_ownership_contract_v1 import classify_canonical_ownership_v1
from engine.astra_trading_reset_boundary_v1 import (
    DUST,
    LEGACY_PRE_RESET_POSITION,
    classify_position_reset_scope_v1,
    determine_reset_boundary_v1,
    _boundary_datetime,
    _iso,
    _num,
    _parse_iso,
    _text,
)


SCHEMA_VERSION = "astra_legacy_retirement_workflow_v1"
RETIREMENT_QUEUE_FILE = "astra_legacy_retirement_queue_v1.json"

LEGACY_EXIT_REVIEW = "LEGACY_EXIT_REVIEW"
LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL = "LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL"
LEGACY_EXIT_APPROVED = "LEGACY_EXIT_APPROVED"
LEGACY_EXIT_PENDING_BROKER = "LEGACY_EXIT_PENDING_BROKER"
LEGACY_EXIT_PARTIALLY_FILLED = "LEGACY_EXIT_PARTIALLY_FILLED"
LEGACY_EXIT_FILLED_AWAITING_ZERO = "LEGACY_EXIT_FILLED_AWAITING_ZERO"
LEGACY_RETIREMENT_COMPLETE = "LEGACY_RETIREMENT_COMPLETE"
LEGACY_DUST_RECONCILIATION = "LEGACY_DUST_RECONCILIATION"
LEGACY_EXIT_BLOCKED = "LEGACY_EXIT_BLOCKED"


def _first_causal_blocker(retirement_state: str, *, thesis_known: bool) -> str:
    """Return the one actionable reason a legacy row cannot advance.

    The queue is intentionally advisory-only.  It must make an absent human
    approval or unavailable thesis explicit instead of presenting a generic
    review state as execution progress.
    """
    if retirement_state == LEGACY_RETIREMENT_COMPLETE:
        return ""
    if retirement_state == LEGACY_DUST_RECONCILIATION:
        return "DUST_POSITION_NOT_TRADABLE"
    if retirement_state in {
        LEGACY_EXIT_PENDING_BROKER,
        LEGACY_EXIT_PARTIALLY_FILLED,
        LEGACY_EXIT_FILLED_AWAITING_ZERO,
    }:
        return "BROKER_RECONCILIATION_REQUIRED"
    if retirement_state == LEGACY_EXIT_BLOCKED and not thesis_known:
        return "ORIGINAL_THESIS_UNAVAILABLE"
    if retirement_state == LEGACY_EXIT_APPROVED:
        return "APPROVED_LEGACY_EXIT_AWAITING_CANONICAL_EXECUTION_HANDOFF"
    return "HUMAN_SELL_APPROVAL_REQUIRED"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(directory), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, separators=(",", ":"), ensure_ascii=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def _load_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    default = dict(default or {})
    if not path.exists():
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass
    return default


def _broker_positions_map(broker_positions: Mapping[str, Any] | list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    if isinstance(broker_positions, Mapping) and broker_positions:
        # Could be a dict keyed by symbol, or a response dict with "positions".
        if "positions" in broker_positions and isinstance(broker_positions["positions"], list):
            positions = broker_positions["positions"]
        elif all(isinstance(v, Mapping) for v in broker_positions.values()):
            return {_text(k).upper(): dict(v) for k, v in broker_positions.items()}
        else:
            positions = []
    elif isinstance(broker_positions, list):
        positions = broker_positions
    else:
        positions = []

    result: dict[str, dict[str, Any]] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        symbol = _text(row.get("symbol")).upper()
        if symbol:
            result[symbol] = dict(row)
    return result


def _position_age_days(position: Mapping[str, Any]) -> float | None:
    ts = _parse_iso(
        position.get("opened_at")
        or position.get("entry_timestamp")
        or position.get("created_at")
    )
    if ts is None:
        return None
    return round((datetime.now(timezone.utc) - ts).total_seconds() / 86400.0, 2)


def classify_retirement_state_v1(
    position: Mapping[str, Any], market_data: Mapping[str, Any] | None = None
) -> str:
    """Assign a non-executing retirement state based on available evidence."""
    row = dict(position or {})
    market = dict(market_data or {})
    dust = bool(
        row.get("dust")
        or row.get("dust_state") == "BROKER_DUST_MONITORED"
        or _num(row.get("quantity") or row.get("qty")) is not None
        and 0.0 < abs(_num(row.get("quantity") or row.get("qty")) or 0.0) < 0.001
    )
    if dust:
        return LEGACY_DUST_RECONCILIATION

    if bool(row.get("retirement_complete")) or (
        _text(row.get("status")).upper() == "CLOSED"
        and bool(row.get("broker_residual_zero_confirmed"))
    ):
        return LEGACY_RETIREMENT_COMPLETE

    if bool(row.get("retirement_exit_filled")) and not bool(
        row.get("broker_residual_zero_confirmed")
    ):
        return LEGACY_EXIT_FILLED_AWAITING_ZERO

    if bool(row.get("retirement_exit_partially_filled")):
        return LEGACY_EXIT_PARTIALLY_FILLED

    if bool(row.get("retirement_exit_submitted")):
        return LEGACY_EXIT_PENDING_BROKER

    if bool(row.get("retirement_human_approved")):
        return LEGACY_EXIT_APPROVED

    unrealized_pct = _num(
        row.get("unrealized_plpc")
        or row.get("unrealized_return_pct")
        or row.get("return_pct")
        or market.get("unrealized_plpc")
    ) or 0.0
    if abs(unrealized_pct) > 1.0:
        unrealized_pct /= 100.0

    known_thesis = bool(
        _text(row.get("original_thesis"))
        or _text(row.get("thesis_state"))
        or _text(row.get("retirement_thesis"))
    )
    liquidity_bad = bool(
        "ILLIQUID" in _text(row.get("liquidity_evidence") or market.get("liquidity_evidence")).upper()
        or "WIDE_SPREAD" in _text(row.get("spread_evidence") or market.get("spread_evidence")).upper()
    )

    if not known_thesis and (unrealized_pct <= -0.10 or liquidity_bad):
        return LEGACY_EXIT_BLOCKED

    if unrealized_pct <= -0.08:
        return LEGACY_EXIT_REVIEW

    if known_thesis and not bool(row.get("retirement_human_approved")):
        return LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL

    return LEGACY_EXIT_REVIEW


def build_legacy_retirement_review_queue_v1(
    positions: list[Mapping[str, Any]],
    broker_positions: Mapping[str, Any] | list[Mapping[str, Any]],
    boundary: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build a review queue for legacy and dust positions.  Does not trade."""
    boundary = boundary or determine_reset_boundary_v1()
    broker_map = _broker_positions_map(broker_positions)
    queue: list[dict[str, Any]] = []

    for position in positions:
        row = dict(position or {})
        classification = classify_position_reset_scope_v1(row, boundary)
        scope = classification.get("reset_scope")
        if scope not in {LEGACY_PRE_RESET_POSITION, DUST}:
            continue

        symbol = _text(row.get("symbol")).upper()
        broker_row = broker_map.get(symbol, {})
        qty = _num(row.get("quantity") or row.get("qty") or broker_row.get("qty")) or 0.0
        market_value = _num(
            row.get("market_value")
            or broker_row.get("market_value")
            or broker_row.get("market_value")
        ) or 0.0
        unrealized_dollar = _num(
            row.get("unrealized_pl")
            or row.get("unrealized_dollar_pl")
            or broker_row.get("unrealized_pl")
        ) or 0.0
        unrealized_pct = _num(
            row.get("unrealized_plpc")
            or row.get("unrealized_return_pct")
            or broker_row.get("unrealized_plpc")
        ) or 0.0
        if abs(unrealized_pct) > 1.0:
            unrealized_pct /= 100.0

        ownership = classify_canonical_ownership_v1(
            row, is_broker_position=True, has_db_record=True
        )
        known_thesis = (
            "KNOWN"
            if _text(row.get("original_thesis")) or _text(row.get("thesis_state"))
            else "UNKNOWN"
        )
        liquidity = _text(
            row.get("liquidity_evidence")
            or broker_row.get("liquidity_evidence")
            or "UNAVAILABLE"
        )
        spread = _text(
            row.get("spread_evidence")
            or broker_row.get("spread_evidence")
            or "UNAVAILABLE"
        )

        retirement_state = classify_retirement_state_v1(row, broker_row)
        first_blocker = _first_causal_blocker(
            retirement_state, thesis_known=known_thesis == "KNOWN"
        )
        sellable_quantity = 0.0 if scope == DUST else max(0.0, qty)

        queue.append({
            "symbol": symbol,
            "quantity": round(qty, 8),
            "dust_status": scope == DUST,
            "current_market_value": round(market_value, 4),
            "current_unrealized_dollar_pl": round(unrealized_dollar, 4),
            "current_unrealized_pct_pl": round(unrealized_pct * 100.0, 4),
            "age_when_provable_days": _position_age_days(row),
            "legacy_classification": ownership.get("ownership_state"),
            "known_or_unknown_original_thesis": known_thesis,
            "liquidity_evidence": liquidity,
            "spread_evidence": spread,
            "retirement_state": retirement_state,
            "final_decision": retirement_state,
            "exact_sellable_quantity": round(sellable_quantity, 8),
            "existing_sell_order": bool(row.get("existing_sell_order") or broker_row.get("existing_sell_order")),
            "execution_authority": "DISABLED",
            "advisory_only": True,
            "first_causal_blocker": first_blocker or None,
            "human_approval_required": retirement_state != LEGACY_RETIREMENT_COMPLETE,
            "broker_zero_confirmation_required": retirement_state
            in {
                LEGACY_EXIT_PENDING_BROKER,
                LEGACY_EXIT_PARTIALLY_FILLED,
                LEGACY_EXIT_FILLED_AWAITING_ZERO,
                LEGACY_RETIREMENT_COMPLETE,
            },
            "reset_scope": scope,
            "reset_reason": classification.get("reset_reason"),
            "position_id": _text(row.get("position_id") or row.get("asset_id") or symbol),
            "reset_id": boundary.get("reset_id"),
            "boundary_timestamp_utc": _iso(_boundary_datetime(boundary)),
        })

    return queue


def save_legacy_retirement_queue_v1(
    queue: list[Mapping[str, Any]], state_dir: str | Path,
    *,
    unclassified_positions: list[Mapping[str, Any]] | None = None,
    provenance_status: str = "",
) -> dict[str, Any]:
    """Persist the retirement review queue atomically."""
    path = Path(state_dir) / RETIREMENT_QUEUE_FILE
    payload = {
        "schema_version": SCHEMA_VERSION,
        "queue": [dict(item) for item in queue],
        "unclassified_positions": [dict(item) for item in (unclassified_positions or [])],
        "provenance_status": _text(provenance_status),
        "saved_at": _iso(),
        "queue_length": len(queue),
    }
    _atomic_write_json(path, payload)
    return {"saved": True, "path": str(path), "queue_length": len(queue)}


def load_legacy_retirement_queue_v1(state_dir: str | Path) -> list[dict[str, Any]]:
    """Load a persisted retirement review queue."""
    path = Path(state_dir) / RETIREMENT_QUEUE_FILE
    payload = _load_json(path, {})
    return [dict(item) for item in (payload.get("queue") or [])]
