"""Strict, cache-only candidate identity and execution-gate validation.

This module is intentionally shared by diagnostics and the final paper-order
boundary.  It never submits orders or fetches data; an ambiguous candidate is
always classified as non-executable.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any


CRYPTO_ASSET_CLASSES = {"crypto", "cryptocurrency"}
SUPPORTED_QUOTES = {"USD", "USDC", "USDT"}
VALID_HORIZONS = {"scalp", "day_trade", "swing_trade"}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _bool(value: Any) -> bool:
    return bool(value)


def _configured_max_spread_pct(candidate: dict[str, Any]) -> float:
    """Use the existing crypto guard configuration without changing it."""
    configured = _number(candidate.get("max_spread_pct"), -1.0)
    if configured < 0:
        configured = _number(os.getenv("ASTRA_CRYPTO_MAX_SPREAD_PCT"), 1.5)
    return max(0.1, configured)


def _timestamp_age_seconds(value: Any) -> float | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def normalize_crypto_pair_strict(
    symbol: Any,
    *,
    asset_class: Any = "",
    known_equity_symbols: set[str] | None = None,
    base_symbol: Any = "",
    quote_currency: Any = "",
) -> dict[str, Any]:
    """Normalize only trusted crypto metadata; never infer crypto from a slash."""
    raw = _text(symbol).upper().replace("-", "/")
    declared = _text(asset_class).lower()
    equities = {str(item or "").upper().strip() for item in (known_equity_symbols or set())}
    if declared not in CRYPTO_ASSET_CLASSES:
        return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_ASSET_CLASS_MISMATCH" if raw else "REJECTED_MISSING_ASSET_METADATA"}
    if not raw:
        return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_SYMBOL_NORMALIZATION"}
    base = _text(base_symbol).upper()
    quote = _text(quote_currency).upper()
    if "/" in raw:
        parts = raw.split("/")
        if len(parts) != 2 or not parts[0] or not parts[1]:
            return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_SYMBOL_NORMALIZATION"}
        base, quote = parts[0].strip(), parts[1].strip()
    elif base and quote:
        pass
    else:
        # Compact pairs are accepted only when the quote is unambiguous.
        matches = [candidate for candidate in SUPPORTED_QUOTES if raw.endswith(candidate) and len(raw) > len(candidate)]
        if len(matches) != 1:
            return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_SYMBOL_NORMALIZATION"}
        quote = matches[0]
        base = raw[: -len(quote)]
    if base in equities:
        return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_EQUITY_SYMBOL_CONTAMINATION"}
    if quote not in SUPPORTED_QUOTES or not base.isalnum():
        return {"ok": False, "normalized_symbol": "", "reason": "REJECTED_SYMBOL_NORMALIZATION"}
    return {"ok": True, "normalized_symbol": f"{base}/{quote}", "reason": "VALID_CRYPTO_PAIR"}


def candidate_execution_integrity(
    candidate: dict[str, Any] | None,
    *,
    supported_pairs: set[str] | list[str] | None = None,
    tradable_pairs: set[str] | list[str] | None = None,
    known_equity_symbols: set[str] | None = None,
    lane_state: str = "LANE_BLOCKED",
    paper_mode_verified: bool = False,
    live_endpoint_detected: bool = False,
    capacity_available: bool = False,
    duplicate_pending: bool = False,
    broker_reconciliation_ok: bool = False,
    kill_switch_enabled: bool = False,
) -> dict[str, Any]:
    """Return a complete mandatory-gate audit with a fail-closed terminal state."""
    row = dict(candidate or {})
    asset_class = _text(row.get("asset_class") or row.get("asset_type")).lower()
    identity = normalize_crypto_pair_strict(
        row.get("symbol") or row.get("ticker"),
        asset_class=asset_class,
        known_equity_symbols=known_equity_symbols,
        base_symbol=row.get("base_symbol"),
        quote_currency=row.get("quote_currency"),
    )
    pair = identity.get("normalized_symbol") or ""
    supported = {str(item or "").upper().replace("-", "/") for item in (supported_pairs or [])}
    tradable = {str(item or "").upper().replace("-", "/") for item in (tradable_pairs or [])}
    quote_age = _number(row.get("quote_age_seconds"), _number(row.get("freshness_seconds"), -1.0))
    if quote_age < 0:
        timestamp_age = _timestamp_age_seconds(row.get("quote_timestamp") or row.get("data_timestamp") or row.get("timestamp"))
        quote_age = timestamp_age if timestamp_age is not None else -1.0
    bid = _number(row.get("bid") or row.get("bid_price") or row.get("bp"), -1.0)
    ask = _number(row.get("ask") or row.get("ask_price") or row.get("ap"), -1.0)
    spread = _number(row.get("spread_pct"), _number(row.get("bid_ask_spread_pct"), -1.0))
    if spread < 0 and bid > 0 and ask > 0 and ask >= bid:
        mid = (bid + ask) / 2.0
        if mid > 0:
            spread = ((ask - bid) / mid) * 100.0
    max_spread_pct = _configured_max_spread_pct(row)
    volume = _number(row.get("volume_24h"), _number(row.get("volume"), _number(row.get("quote_volume"), 0.0)))
    quality = _number(row.get("data_quality_score"), _number(row.get("quote_quality_score"), 0.0))
    confidence = _number(row.get("confidence"), _number(row.get("ranking_score"), _number(row.get("score"), 0.0)))
    if 0 < confidence <= 1:
        confidence *= 100.0
    horizon = _text(row.get("paper_entry_horizon_style") or row.get("assigned_horizon") or row.get("trade_horizon_style")).lower()
    if horizon == "intraday":
        horizon = "day_trade"
    gates = {
        "identity": "PASS" if identity.get("ok") else identity.get("reason"),
        "broker_support": "PASS" if pair and pair in supported else "REJECTED_UNSUPPORTED_CRYPTO_PAIR",
        "broker_tradability": "PASS" if pair and pair in tradable else "REJECTED_UNTRADABLE_CRYPTO_PAIR",
        "timestamp_freshness": "PASS" if 0 <= quote_age <= 120 else "PENDING_QUOTE_FRESHNESS" if quote_age < 0 else "REJECTED_STALE_QUOTE",
        "quote_spread": "PASS" if 0 <= spread <= max_spread_pct else "PENDING_SPREAD" if spread < 0 else "REJECTED_EXCESSIVE_SPREAD",
        "volume_liquidity": "PASS" if volume > 0 else "PENDING_LIQUIDITY",
        "data_quality": "PASS" if quality >= 50 else "PENDING_DATA_QUALITY",
        "volatility_risk": "PASS" if _text(row.get("volatility_risk_status") or "pass").lower() not in {"blocked", "reject", "high"} else "REJECTED_VOLATILITY_RISK",
        "duplicate_pending": "REJECTED_DUPLICATE_OR_PENDING" if duplicate_pending or _bool(row.get("duplicate_pending_order")) else "PASS",
        "capacity_concentration": "PASS" if capacity_available and _text(row.get("concentration_status") or "pass").lower() not in {"blocked", "reject"} else "PENDING_CAPACITY_OR_CONCENTRATION",
        "broker_reconciliation": "PASS" if broker_reconciliation_ok else "PENDING_BROKER_RECONCILIATION",
        "paper_live_safety": "PASS" if paper_mode_verified and not live_endpoint_detected and not kill_switch_enabled else "REJECTED_PAPER_LIVE_SAFETY",
        "confidence_ranking": "PASS" if confidence >= 52 else "PENDING_CONFIDENCE_OR_RANKING",
        "horizon_assignment": "PASS" if horizon in VALID_HORIZONS and horizon != "scalp" else "PENDING_HORIZON_ASSIGNMENT",
        "order_schema_min_notional": "PASS" if _number(row.get("notional"), 25.0) >= 1.0 else "REJECTED_MIN_NOTIONAL",
        "budget": "PASS" if _text(row.get("budget_status") or "pass").lower() not in {"blocked", "reject"} else "REJECTED_BUDGET",
        "kill_switch": "REJECTED_KILL_SWITCH" if kill_switch_enabled else "PASS",
    }
    failed = [name for name, status in gates.items() if status != "PASS"]
    eligible = not failed and lane_state == "LANE_PAPER_ACTIVE_BOUNDED"
    if identity.get("reason") in {"REJECTED_EQUITY_SYMBOL_CONTAMINATION", "REJECTED_ASSET_CLASS_MISMATCH", "REJECTED_MISSING_ASSET_METADATA", "REJECTED_SYMBOL_NORMALIZATION"}:
        candidate_state = "REJECTED_ASSET_CLASS"
    elif not identity.get("ok"):
        candidate_state = "REJECTED_UNVERIFIED"
    elif eligible:
        candidate_state = "BROKER_ELIGIBLE"
    elif failed:
        candidate_state = "DATA_INCOMPLETE" if any(status.startswith("PENDING_") for status in gates.values()) else "REJECTED"
    else:
        candidate_state = "GATE_PENDING"
    return {
        "normalized_symbol": pair or None,
        "identity_status": identity.get("reason"),
        "candidate_state": candidate_state,
        "execution_eligible": eligible,
        "gate_status": gates,
        "failed_gates": failed,
        "quote_age_seconds": round(quote_age, 3) if quote_age >= 0 else None,
        "spread_pct": spread if spread >= 0 else None,
        "bid": bid if bid > 0 else None,
        "ask": ask if ask > 0 else None,
        "mid": round((bid + ask) / 2.0, 10) if bid > 0 and ask > 0 and ask >= bid else None,
        "max_spread_pct": max_spread_pct,
        "volume_24h": volume,
        "data_quality_score": quality,
        "confidence": round(confidence, 2),
        "assigned_horizon": horizon or "unknown",
        "lane_state": lane_state,
        "semantic_fail_closed": bool(failed),
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "broker_actions_used": 0,
        "behavior_safe_to_apply": False,
        "advisory_only": True,
    }
