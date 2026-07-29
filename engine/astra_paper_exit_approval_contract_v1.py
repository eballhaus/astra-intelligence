"""Canonical paper-sell approval contract — one gate for all broker sell paths."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Mapping


SCHEMA_VERSION = "astra_paper_exit_approval_contract_v1"

APPROVAL_STATUSES = frozenset({"PENDING", "APPROVED", "CONSUMED", "EXPIRED", "REVOKED", "REJECTED"})

VALID_SIDES = frozenset({"SELL"})


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float | None = None) -> float | None:
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def build_paper_sell_approval_v1(
    *,
    approved_by: str,
    approved_symbol: str,
    approved_quantity: float,
    approved_account: str = "",
    approved_policy: str = "human_explicit",
    approved_action: str = "SELL",
    approved_decision_id: str = "",
    expires_in_minutes: float = 120.0,
    approved_max_quantity: float | None = None,
    approved_account_fingerprint: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a canonical paper-sell approval. Requires human identity."""
    if not _text(approved_by):
        raise ValueError("approved_by is required for human approval")
    if not _text(approved_symbol):
        raise ValueError("approved_symbol is required")
    if (approved_quantity or 0.0) <= 0.0:
        raise ValueError("approved_quantity must be positive")

    current = now or datetime.now(timezone.utc)
    as_of = _iso(current)
    expires = _iso(current) if expires_in_minutes <= 0 else _iso(
        datetime.fromtimestamp(current.timestamp() + expires_in_minutes * 60, tz=timezone.utc)
    )

    return {
        "schema_version": SCHEMA_VERSION,
        "approval_id": f"apr:{uuid.uuid4().hex}",
        "approval_status": "APPROVED",
        "approved_by": _text(approved_by),
        "approved_at": as_of,
        "approval_expires_at": expires,
        "approved_account": _text(approved_account),
        "approved_account_fingerprint": _text(approved_account_fingerprint),
        "approved_symbol": _text(approved_symbol).upper(),
        "approved_side": "SELL",
        "approved_action": _text(approved_action or "SELL").upper(),
        "approved_quantity": float(approved_quantity),
        "approved_max_quantity": float(approved_max_quantity or approved_quantity),
        "approved_policy": _text(approved_policy),
        "approved_decision_id": _text(approved_decision_id),
        "approval_source": "human_explicit",
        "consumed_at": "",
        "consumed_by_order_intent_id": "",
        "revoked_at": "",
        "revocation_reason": "",
    }


def validate_paper_sell_approval_v1(
    approval: Mapping[str, Any] | None,
    *,
    symbol: str,
    quantity: float,
    account: str = "",
    account_fingerprint: str = "",
    side: str = "SELL",
    action: str = "SELL",
    decision_id: str = "",
    policy: str = "",
    paper_mode_verified: bool = True,
    live_endpoint_detected: bool = False,
    kill_switch_active: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Validate a paper-sell approval before any broker call.

    Returns {"valid": True, ...} or {"valid": False, "reason": ...}.
    All failures close the gate — no defaults, no fallbacks.
    """
    current = now or datetime.now(timezone.utc)

    if kill_switch_active:
        return {"valid": False, "reason": "KILL_SWITCH_ACTIVE", "blocker": "kill_switch"}

    if not paper_mode_verified:
        return {"valid": False, "reason": "PAPER_MODE_NOT_VERIFIED", "blocker": "paper_mode"}

    if live_endpoint_detected:
        return {"valid": False, "reason": "LIVE_ENDPOINT_DETECTED", "blocker": "live_endpoint"}

    if not isinstance(approval, dict) or not approval:
        return {"valid": False, "reason": "APPROVAL_MISSING", "blocker": "approval_missing"}

    appr = dict(approval)

    status = _text(appr.get("approval_status")).upper()
    if status != "APPROVED":
        return {"valid": False, "reason": f"APPROVAL_NOT_ACTIVE:{status}", "blocker": "approval_status"}

    approval_id = _text(appr.get("approval_id"))
    if not approval_id:
        return {"valid": False, "reason": "APPROVAL_ID_MISSING", "blocker": "approval_id"}

    approved_by = _text(appr.get("approved_by"))
    if not approved_by:
        return {"valid": False, "reason": "APPROVED_BY_MISSING", "blocker": "approved_by"}

    approved_at = _parse_iso(appr.get("approved_at"))
    if not approved_at:
        return {"valid": False, "reason": "APPROVED_AT_INVALID", "blocker": "approved_at"}

    if approved_at > current:
        return {"valid": False, "reason": "APPROVAL_FUTURE_TIMESTAMP", "blocker": "approved_at_future"}

    expires_at = _parse_iso(appr.get("approval_expires_at"))
    if expires_at and expires_at < current:
        return {"valid": False, "reason": "APPROVAL_EXPIRED", "blocker": "expired"}

    consumed_at = _text(appr.get("consumed_at"))
    if consumed_at:
        return {"valid": False, "reason": "APPROVAL_ALREADY_CONSUMED", "blocker": "already_consumed"}

    revoked_at = _text(appr.get("revoked_at"))
    if revoked_at:
        return {
            "valid": False,
            "reason": f"APPROVAL_REVOKED:{appr.get('revocation_reason', '')}",
            "blocker": "revoked",
        }

    approved_symbol = _text(appr.get("approved_symbol")).upper()
    if approved_symbol != _text(symbol).upper():
        return {
            "valid": False,
            "reason": f"SYMBOL_MISMATCH:{approved_symbol}v{_text(symbol).upper()}",
            "blocker": "symbol_mismatch",
        }
    if _text(appr.get("approved_account")) and _text(appr.get("approved_account")) != _text(account):
        return {"valid": False, "reason": "ACCOUNT_MISMATCH", "blocker": "account_mismatch"}
    if _text(appr.get("approved_account_fingerprint")) and _text(appr.get("approved_account_fingerprint")) != _text(account_fingerprint):
        return {"valid": False, "reason": "ACCOUNT_FINGERPRINT_MISMATCH", "blocker": "account_mismatch"}

    approved_side = _text(appr.get("approved_side")).upper()
    if approved_side != _text(side).upper():
        return {
            "valid": False,
            "reason": f"SIDE_MISMATCH:{approved_side}v{_text(side).upper()}",
            "blocker": "side_mismatch",
        }

    approved_action = _text(appr.get("approved_action")).upper()
    if approved_action and _text(action).upper() and approved_action != _text(action).upper():
        return {
            "valid": False,
            "reason": f"ACTION_MISMATCH:{approved_action}v{_text(action).upper()}",
            "blocker": "action_mismatch",
        }

    approved_account = _text(appr.get("approved_account"))
    if approved_account and _text(account) and approved_account != _text(account):
        return {
            "valid": False,
            "reason": f"ACCOUNT_MISMATCH:{approved_account}v{_text(account)}",
            "blocker": "account_mismatch",
        }

    approved_policy = _text(appr.get("approved_policy"))
    if approved_policy and _text(policy) and approved_policy != _text(policy):
        return {
            "valid": False,
            "reason": f"POLICY_MISMATCH:{approved_policy}v{_text(policy)}",
            "blocker": "policy_mismatch",
        }

    approved_decision = _text(appr.get("approved_decision_id"))
    if approved_decision and _text(decision_id) and approved_decision != _text(decision_id):
        return {
            "valid": False,
            "reason": f"DECISION_MISMATCH:{approved_decision}v{_text(decision_id)}",
            "blocker": "decision_mismatch",
        }

    max_qty = _num(appr.get("approved_max_quantity")) or _num(appr.get("approved_quantity")) or 0.0
    if float(quantity) > float(max_qty):
        return {
            "valid": False,
            "reason": f"QUANTITY_EXCEEDS_APPROVED:{quantity}v{max_qty}",
            "blocker": "quantity_exceeded",
        }

    return {
        "valid": True,
        "reason": "APPROVED",
        "approval_id": approval_id,
        "approved_by": approved_by,
        "approved_quantity": max_qty,
    }


def consume_paper_sell_approval_v1(
    approval: dict[str, Any],
    *,
    order_intent_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Mark an approval as consumed atomically with order intent creation."""
    result = dict(approval)
    result["consumed_at"] = _iso(now)
    result["consumed_by_order_intent_id"] = _text(order_intent_id)
    result["approval_status"] = "CONSUMED"
    return result
