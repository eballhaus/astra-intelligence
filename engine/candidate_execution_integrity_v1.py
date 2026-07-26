"""Strict, cache-only candidate identity and execution-gate validation.

This module is intentionally shared by diagnostics and the final paper-order
boundary.  It never submits orders or fetches data; an ambiguous candidate is
always classified as non-executable.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


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


def derive_crypto_horizon_evidence_v1(candidate: Mapping[str, Any] | None) -> dict[str, Any]:
    """Build a deterministic, persisted crypto-horizon evidence envelope.

    This is deliberately not a ranking adjustment and never supplies a
    fallback horizon.  The producer must provide a completed-bar window,
    directional bar return, risk range, confidence, and an explicit regime
    observation.  Missing source facts remain visible and fail closed.
    """
    row = dict(candidate or {})
    bars = dict(row.get("bar_evidence") or {})
    completed = int(_number(bars.get("completed_bar_count") or bars.get("count"), 0.0))
    volume = _number(bars.get("rolling_completed_bar_volume") or row.get("volume") or row.get("quote_volume"), 0.0)
    momentum = _number(row.get("completed_bar_return_pct") or row.get("crypto_completed_bar_return_pct"), 0.0)
    risk = _number(row.get("crypto_risk_pct"), 0.0)
    confidence = _number(row.get("confidence") or row.get("ranking_score") or row.get("score"), 0.0)
    if 0 < confidence <= 1:
        confidence *= 100.0
    regime = _text(row.get("market_regime") or row.get("regime") or row.get("external_environment_tier") or (row.get("ranking_feedback_profile") or {}).get("external_environment_tier"))
    missing: list[str] = []
    if completed < 8:
        missing.append("COMPLETED_15MIN_BAR_WINDOW_INSUFFICIENT")
    if volume <= 0:
        missing.append("COMPLETED_BAR_VOLUME_MISSING")
    if not row.get("quote_timestamp"):
        missing.append("QUOTE_TIMESTAMP_MISSING")
    if risk <= 0:
        missing.append("BAR_RISK_ENVELOPE_MISSING")
    if momentum == 0:
        missing.append("DIRECTIONAL_COMPLETED_BAR_RETURN_MISSING")
    if confidence <= 0:
        missing.append("RANKING_CONFIDENCE_MISSING")
    if not regime:
        missing.append("REGIME_OBSERVATION_MISSING")
    if missing:
        return {
            "horizon_evidence_status": "INSUFFICIENT_EVIDENCE",
            "horizon_evidence_missing": missing,
            "assigned_horizon": None,
            "paper_entry_horizon_style": None,
            "horizon_scores": {},
            "horizon_provenance": "crypto_15m_completed_bar_horizon_v1",
            "horizon_assignment_version": "1.0.0",
            "horizon_confidence": 0.0,
        }
    # The 15-minute completed-bar source proves an intraday window only.  It
    # cannot justify a fabricated scalp or swing assignment.
    directional_strength = min(20.0, abs(momentum) * 100.0)
    evidence_strength = min(20.0, completed / 2.0) + min(20.0, max(0.0, confidence) / 5.0)
    day_score = round(min(100.0, 40.0 + directional_strength + evidence_strength + min(20.0, risk * 4.0)), 2)
    return {
        "horizon_evidence_status": "PERSISTED_CANONICAL",
        "horizon_evidence_missing": [],
        "assigned_horizon": "day_trade",
        "paper_entry_horizon_style": "day_trade",
        "horizon_scores": {"scalp": 0.0, "day_trade": day_score, "swing_trade": 0.0},
        "horizon_provenance": "crypto_15m_completed_bar_horizon_v1",
        "horizon_assignment_version": "1.0.0",
        "horizon_confidence": day_score,
        "horizon_evidence": {
            "resolution": bars.get("resolution"), "completed_bar_count": completed,
            "completed_bar_return_pct": round(momentum, 6), "rolling_completed_bar_volume": volume,
            "risk_pct": risk, "regime": regime,
        },
    }


def derive_crypto_pretrade_forecast_v1(
    candidate: Mapping[str, Any] | None,
    *,
    completed_bars: list[Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Derive a bounded CRYPTO continuation forecast from completed bars.

    The worker already owns the quote and completed-bar request that establish
    crypto candidate freshness.  This helper turns those same authoritative
    inputs into explicit forecast, target, and risk fields for the canonical
    pretrade contract.  It deliberately declines to forecast when either the
    latest completed-bar momentum or the bounded trend disagrees; no default
    target, return, or stop is supplied to make a candidate executable.
    """
    row = dict(candidate or {})
    source_bars = completed_bars if completed_bars is not None else row.get("completed_bars")
    bars = [dict(item) for item in (source_bars or []) if isinstance(item, Mapping)]
    parsed: list[dict[str, float | str]] = []
    for bar in bars[-24:]:
        close = _number(bar.get("c") if "c" in bar else bar.get("close"), -1.0)
        high = _number(bar.get("h") if "h" in bar else bar.get("high"), -1.0)
        low = _number(bar.get("l") if "l" in bar else bar.get("low"), -1.0)
        timestamp = _text(bar.get("t") or bar.get("timestamp"))
        if close > 0 and high >= close and 0 < low <= close and timestamp:
            parsed.append({"close": close, "high": high, "low": low, "timestamp": timestamp})
    price = _number(row.get("price") or row.get("current_price") or row.get("last_price"), -1.0)
    if price <= 0 and parsed:
        price = float(parsed[-1]["close"])
    horizon = _text(row.get("paper_entry_horizon_style") or row.get("assigned_horizon") or row.get("trade_horizon_style"))
    observation_timestamp = _text(row.get("provider_quote_timestamp") or row.get("quote_timestamp"))
    bar_timestamp = _text(row.get("bar_timestamp") or (parsed[-1]["timestamp"] if parsed else ""))
    risk_pct = _number(row.get("crypto_risk_pct") or row.get("risk_pct") or row.get("atr_pct"), 0.0)
    latest_return_pct = _number(row.get("completed_bar_return_pct") or row.get("crypto_completed_bar_return_pct"), 0.0)
    if latest_return_pct == 0.0 and len(parsed) >= 2:
        prior_close = float(parsed[-2]["close"])
        latest_return_pct = ((float(parsed[-1]["close"]) - prior_close) / prior_close) * 100.0 if prior_close > 0 else 0.0
    window = parsed[-8:]
    trend_pct = 0.0
    if len(window) >= 2:
        first_close = float(window[0]["close"])
        if first_close > 0:
            trend_pct = ((float(window[-1]["close"]) - first_close) / first_close) * 100.0
    missing: list[str] = []
    if len(window) < 8:
        missing.append("COMPLETED_15MIN_BAR_WINDOW_INSUFFICIENT")
    if price <= 0:
        missing.append("CURRENT_PRICE_MISSING")
    if not observation_timestamp:
        missing.append("PROVIDER_QUOTE_TIMESTAMP_MISSING")
    if not bar_timestamp:
        missing.append("COMPLETED_BAR_TIMESTAMP_MISSING")
    if risk_pct <= 0:
        missing.append("BAR_RISK_ENVELOPE_MISSING")
    if latest_return_pct <= 0:
        missing.append("LATEST_COMPLETED_BAR_CONTINUATION_NOT_POSITIVE")
    if trend_pct <= 0:
        missing.append("BOUNDED_COMPLETED_BAR_TREND_NOT_POSITIVE")
    if horizon != "day_trade":
        missing.append("UNSUPPORTED_CRYPTO_FORECAST_HORIZON")
    if missing:
        return {
            "forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE",
            "calculation_method": "crypto_completed_bar_continuation_v1",
            "schema_version": "1.0.0",
            "missing_inputs": missing,
            "source_inputs": {
                "completed_bar_count": len(parsed), "latest_completed_bar_return_pct": round(latest_return_pct, 6),
                "bounded_trend_pct": round(trend_pct, 6), "crypto_risk_pct": round(risk_pct, 6),
                "observation_timestamp": observation_timestamp, "bar_timestamp": bar_timestamp,
            },
            "source_provenance": {
                "source_system": "PaperAutopilotWorker.crypto_rankings_snapshot_v1",
                "source_fields": ["completed_15min_bars", "provider_quote_timestamp", "crypto_risk_pct"],
                "evidence_class": "CURRENT_CANDIDATE_DIRECT",
            },
        }
    # Both continuation measures are observed completed-bar returns.  The
    # lower target uses their weaker positive observation; the higher target
    # extends the stronger observation by one currently observed bar range.
    # This preserves an explicit, bounded calculation instead of a fixed
    # crypto return or target percentage.
    low_pct = min(latest_return_pct, trend_pct)
    high_pct = max(latest_return_pct, trend_pct) + risk_pct
    if low_pct <= 0 or high_pct <= 0:
        return {
            "forecast_state": "INSUFFICIENT_FORECAST_EVIDENCE",
            "calculation_method": "crypto_completed_bar_continuation_v1",
            "schema_version": "1.0.0",
            "missing_inputs": ["POSITIVE_CONTINUATION_RANGE_UNAVAILABLE"],
            "source_inputs": {"latest_completed_bar_return_pct": latest_return_pct, "bounded_trend_pct": trend_pct, "crypto_risk_pct": risk_pct},
            "source_provenance": {"source_system": "PaperAutopilotWorker.crypto_rankings_snapshot_v1", "evidence_class": "CURRENT_CANDIDATE_DIRECT"},
        }
    support = min(float(bar["low"]) for bar in window)
    invalidation = support if 0 < support < price else None
    downside_low = ((invalidation - price) / price) * 100.0 if invalidation else -risk_pct
    generated_time = now or datetime.now(timezone.utc)
    generated_at = generated_time.isoformat().replace("+00:00", "Z")
    target_low = price * (1.0 + low_pct / 100.0)
    target_high = price * (1.0 + high_pct / 100.0)
    return {
        "forecast_state": "FORECAST_COMPLETE",
        "schema_version": "1.0.0",
        "calculation_method": "crypto_completed_bar_continuation_v1",
        "forecast_timestamp": generated_at,
        "valid_until": (generated_time + timedelta(seconds=120)).isoformat().replace("+00:00", "Z"),
        "expected_return_range": {"low_pct": round(low_pct, 6), "high_pct": round(high_pct, 6), "evidence_label": "COMPLETED_BAR_CONTINUATION"},
        "expected_return_pct": round((low_pct + high_pct) / 2.0, 6),
        "expected_target_low": round(target_low, 8),
        "expected_target_high": round(target_high, 8),
        "expected_downside_range": {"low_pct": round(min(downside_low, -risk_pct), 6), "high_pct": round(max(downside_low, -risk_pct), 6), "evidence_label": "COMPLETED_BAR_RISK"},
        "expected_drawdown": {"low_pct": round(-2.0 * risk_pct, 6), "high_pct": round(-risk_pct, 6), "evidence_label": "COMPLETED_BAR_VOLATILITY"},
        "invalidation_level": round(invalidation, 8) if invalidation else None,
        "source_inputs": {
            "completed_bar_count": len(parsed), "latest_completed_bar_return_pct": round(latest_return_pct, 6),
            "bounded_trend_pct": round(trend_pct, 6), "crypto_risk_pct": round(risk_pct, 6),
            "current_price": round(price, 8), "observation_timestamp": observation_timestamp,
            "bar_timestamp": bar_timestamp, "horizon": horizon,
        },
        "source_provenance": {
            "source_system": "PaperAutopilotWorker.crypto_rankings_snapshot_v1",
            "source_fields": ["completed_15min_bars", "provider_quote_timestamp", "crypto_risk_pct", "paper_entry_horizon_style"],
            "evidence_class": "CURRENT_CANDIDATE_DIRECT",
            "observation_timestamp": observation_timestamp,
            "bar_timestamp": bar_timestamp,
        },
    }


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
    capacity_fact: Mapping[str, Any] | None = None,
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
    # Production crypto rows retain the provider timestamp explicitly.  A
    # worker receipt time must never make an otherwise unproven quote fresh.
    provider_quote_timestamp = row.get("provider_quote_timestamp") or row.get("quote_timestamp")
    timestamp_age = _timestamp_age_seconds(provider_quote_timestamp)
    quote_age = timestamp_age if timestamp_age is not None else _number(
        row.get("quote_age_seconds"), _number(row.get("freshness_seconds"), -1.0)
    )
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
    horizon_status = _text(row.get("horizon_evidence_status"))
    horizon_missing = list(row.get("horizon_evidence_missing") or [])
    canonical_horizon = bool(
        horizon in VALID_HORIZONS
        and horizon != "scalp"
        and horizon_status == "PERSISTED_CANONICAL"
        and _text(row.get("horizon_provenance"))
        and isinstance(row.get("horizon_scores"), dict)
    )
    fact = dict(capacity_fact or {})
    if fact:
        capacity_gate = "PASS" if bool(fact.get("allowed")) and bool(fact.get("authority_current")) else (
            "PENDING_CANONICAL_CAPACITY_AUTHORITY" if not bool(fact.get("authority_current")) else "PENDING_" + _text(fact.get("capacity_decision") or "CAPACITY")
        )
    else:
        # Compatibility is retained only for direct legacy callers. Production
        # crypto paths inject the canonical fact and cannot clear this gate.
        capacity_gate = "PASS" if capacity_available else "PENDING_CAPACITY_OR_CONCENTRATION"
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
        "capacity_concentration": capacity_gate if _text(row.get("concentration_status") or "pass").lower() not in {"blocked", "reject"} else "PENDING_CAPACITY_OR_CONCENTRATION",
        "broker_reconciliation": "PASS" if broker_reconciliation_ok else "PENDING_BROKER_RECONCILIATION",
        "paper_live_safety": "PASS" if paper_mode_verified and not live_endpoint_detected and not kill_switch_enabled else "REJECTED_PAPER_LIVE_SAFETY",
        # This records the pre-existing lane activation guard in the same
        # causal contract. It does not activate a lane or alter execution.
        "lane_activation": "PASS" if lane_state == "LANE_PAPER_ACTIVE_BOUNDED" else "PENDING_LANE_ACTIVATION",
        "confidence_ranking": "PASS" if confidence >= 52 else "PENDING_CONFIDENCE_OR_RANKING",
        "horizon_assignment": "PASS" if canonical_horizon else "PENDING_HORIZON_EVIDENCE:" + (horizon_missing[0] if horizon_missing else "NOT_PERSISTED_CANONICAL"),
        "order_schema_min_notional": "PASS" if _number(row.get("notional"), 25.0) >= 1.0 else "REJECTED_MIN_NOTIONAL",
        "budget": "PASS" if _text(row.get("budget_status") or "pass").lower() not in {"blocked", "reject"} else "REJECTED_BUDGET",
        "kill_switch": "REJECTED_KILL_SWITCH" if kill_switch_enabled else "PASS",
    }
    failed = [name for name, status in gates.items() if status != "PASS"]
    # Dict insertion order is the canonical gate order.  Consumers use this
    # one first failure rather than incorrectly elevating downstream symptoms.
    first_gate = failed[0] if failed else ""
    first_causal_blocker = {
        "gate": first_gate,
        "status": gates.get(first_gate, ""),
        "evidence_class": "MARKET_EVIDENCE" if first_gate in {
            "timestamp_freshness", "quote_spread", "volume_liquidity", "data_quality"
        } else "EXECUTION_GUARD",
    } if first_gate else None
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
        "first_causal_blocker": first_causal_blocker,
        "quote_age_seconds": round(quote_age, 3) if quote_age >= 0 else None,
        "provider_quote_timestamp": provider_quote_timestamp or None,
        "spread_pct": spread if spread >= 0 else None,
        "bid": bid if bid > 0 else None,
        "ask": ask if ask > 0 else None,
        "mid": round((bid + ask) / 2.0, 10) if bid > 0 and ask > 0 and ask >= bid else None,
        "max_spread_pct": max_spread_pct,
        "volume_24h": volume,
        "data_quality_score": quality,
        "confidence": round(confidence, 2),
        "assigned_horizon": horizon or "unknown",
        "horizon_evidence_status": horizon_status or "INSUFFICIENT_EVIDENCE",
        "horizon_evidence_missing": horizon_missing,
        "capacity_fact": fact or None,
        "lane_state": lane_state,
        "semantic_fail_closed": bool(failed),
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "broker_actions_used": 0,
        "behavior_safe_to_apply": False,
        "advisory_only": True,
    }
