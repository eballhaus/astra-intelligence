"""Non-executing legacy position retirement review queue.

This module produces an advisory review queue for positions whose reset scope is
``LEGACY_PRE_RESET_POSITION`` or ``DUST``.  It never submits broker orders,
changes sell protections, or alters central execution.
"""
from __future__ import annotations

import json
import os
import tempfile
import hashlib
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
RETIREMENT_EXECUTION_FILE = "astra_legacy_retirement_execution_v1.json"

LEGACY_EXIT_REVIEW = "LEGACY_EXIT_REVIEW"
LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL = "LEGACY_EXIT_READY_FOR_HUMAN_APPROVAL"
LEGACY_EXIT_APPROVED = "LEGACY_EXIT_APPROVED"
LEGACY_EXIT_PENDING_BROKER = "LEGACY_EXIT_PENDING_BROKER"
LEGACY_EXIT_PARTIALLY_FILLED = "LEGACY_EXIT_PARTIALLY_FILLED"
LEGACY_EXIT_FILLED_AWAITING_ZERO = "LEGACY_EXIT_FILLED_AWAITING_ZERO"
LEGACY_RETIREMENT_COMPLETE = "LEGACY_RETIREMENT_COMPLETE"
LEGACY_DUST_RECONCILIATION = "LEGACY_DUST_RECONCILIATION"
LEGACY_EXIT_BLOCKED = "LEGACY_EXIT_BLOCKED"


def _execution_id(*parts: str) -> str:
    """Stable idempotency identity for one owner-approved legacy retirement."""
    return "legacy-retire-" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def build_legacy_retirement_owner_approval_v1(
    *, owner: str, symbols: list[str], approved_at: str, paper_account: str,
    approval_scope: str = "ALPACA_PAPER_LEGACY_RETIREMENT_ONLY",
) -> dict[str, Any]:
    """Create a durable, paper-only approval scope; it never authorizes live trading."""
    approved = sorted({_text(symbol).upper() for symbol in symbols if _text(symbol)})
    if not _text(owner) or not approved or not _text(paper_account):
        raise ValueError("owner, paper account, and approved symbols are required")
    approval_id = _execution_id(owner, paper_account, approved_at, ",".join(approved))
    return {
        "schema_version": SCHEMA_VERSION,
        "approval_id": approval_id,
        "approval_status": "APPROVED",
        "approved_by": _text(owner),
        "approved_at": _text(approved_at),
        "approval_scope": _text(approval_scope),
        "paper_account": _text(paper_account),
        "approved_symbols": approved,
        "paper_only": True,
        "live_trading_authorized": False,
        "execution_authority": "HUMAN_APPROVED_PAPER_ONLY",
        "consumed_intent_ids": [],
    }


def evaluate_legacy_current_thesis_v1(
    position: Mapping[str, Any], evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Require fresh current evidence for a hold; never reconstruct an old thesis."""
    row, current = dict(position or {}), dict(evidence or {})
    freshness = _text(current.get("freshness_status") or current.get("evidence_status")).upper()
    thesis = _text(current.get("current_thesis") or current.get("thesis_state")).upper()
    if freshness not in {"FRESH", "CURRENT"}:
        return {"decision": "BLOCKED_WITH_EXACT_CAUSE", "first_causal_blocker": "CURRENT_THESIS_EVIDENCE_NOT_FRESH"}
    if thesis in {"VALID", "SUPPORTED", "CURRENT_LOGIC_SUPPORTED"}:
        return {"decision": "CURRENT_LOGIC_HOLD_WITH_VERIFIED_THESIS", "first_causal_blocker": ""}
    return {"decision": "LEGACY_EXIT_READY", "first_causal_blocker": "NO_CURRENT_VERIFIED_THESIS"}


def preflight_legacy_retirement_execution_v1(
    retirement: Mapping[str, Any], broker_position: Mapping[str, Any] | None,
    approval: Mapping[str, Any] | None, safety: Mapping[str, Any] | None,
    market: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Fail-closed canonical preflight used before a legacy paper sell intent.

    This contract only determines eligibility. Submission, broker acknowledgement,
    and broker-zero closure remain owned by PaperAutopilot's shared sell path.
    """
    row, broker, approved, safe, quote = (dict(retirement or {}), dict(broker_position or {}),
                                           dict(approval or {}), dict(safety or {}), dict(market or {}))
    symbol = _text(row.get("symbol")).upper()
    qty = _num(broker.get("qty_available") or broker.get("qty")) or 0.0
    blockers: list[str] = []
    if not symbol or _text(broker.get("symbol")).upper() != symbol:
        blockers.append("BROKER_SYMBOL_MISMATCH")
    if qty <= 0:
        blockers.append("BROKER_SELLABLE_QUANTITY_UNAVAILABLE")
    if bool(row.get("dust_status")):
        blockers.append("DUST_POSITION_NOT_TRADABLE")
    if not bool(safe.get("paper_mode_verified")) or bool(safe.get("live_endpoint_detected")) or bool(safe.get("broker_live_endpoint_allowed")):
        blockers.append("PAPER_ONLY_BROKER_BOUNDARY_REQUIRED")
    if _text(approved.get("approval_status")).upper() != "APPROVED" or symbol not in set(approved.get("approved_symbols") or []):
        blockers.append("OWNER_APPROVAL_REQUIRED")
    if not bool(quote.get("market_session_open")):
        blockers.append("MARKET_CLOSED")
    if not bool(quote.get("executable_freshness")) or _text(quote.get("freshness_status")).upper() not in {"FRESH", "CURRENT"}:
        blockers.append("STALE_OR_MISSING_EXECUTABLE_QUOTE")
    if not bool(broker.get("tradable", True)):
        blockers.append("BROKER_SYMBOL_NOT_TRADABLE")
    if bool(row.get("existing_sell_order")):
        blockers.append("EXISTING_SELL_ORDER")
    intent_id = _execution_id(str(approved.get("approval_id") or ""), symbol, str(row.get("position_id") or broker.get("asset_id") or ""))
    return {
        "preflight_status": "PASS" if not blockers else "BLOCKED",
        "first_causal_blocker": blockers[0] if blockers else "",
        "blockers": blockers,
        "symbol": symbol,
        "broker_quantity": round(qty, 8),
        "intent_id": intent_id,
        "order_type": "market",
        "time_in_force": "day",
        "paper_only": True,
        "live_trading_authorized": False,
    }


def save_legacy_retirement_execution_v1(payload: Mapping[str, Any], state_dir: str | Path) -> dict[str, Any]:
    path = Path(state_dir) / RETIREMENT_EXECUTION_FILE
    value = {"schema_version": SCHEMA_VERSION, "saved_at": _iso(), **dict(payload or {})}
    _atomic_write_json(path, value)
    return value


def load_legacy_retirement_execution_v1(state_dir: str | Path) -> dict[str, Any]:
    return _load_json(Path(state_dir) / RETIREMENT_EXECUTION_FILE, {})


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
