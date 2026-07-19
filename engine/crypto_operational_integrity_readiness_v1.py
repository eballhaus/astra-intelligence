"""Cache-only crypto paper-lane readiness composition.

This module owns no execution policy.  It composes the existing lane-capital,
broker-capability, and candidate-integrity contracts into one bounded,
read-only readiness payload for diagnostics and worker snapshots.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

from engine.candidate_execution_integrity_v1 import candidate_execution_integrity, normalize_crypto_pair_strict

VERSION = "1.0.0"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _num(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value not in (None, "") else float(default)
    except (TypeError, ValueError):
        return float(default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _timestamp_age_seconds(value: Any) -> float | None:
    text = _text(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0.0, (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds())
    except (TypeError, ValueError):
        return None


def _capability_freshness(capability: dict[str, Any]) -> dict[str, Any]:
    age = _timestamp_age_seconds(capability.get("generated_at"))
    raw_ttl = _text(os.getenv("ASTRA_CRYPTO_CAPABILITY_MAX_AGE_SECONDS"))
    configured_ttl = _num(raw_ttl, -1.0) if raw_ttl else None
    if age is None:
        state = "UNKNOWN"
    elif age <= 86400:
        state = "CURRENT"
    elif age <= 604800:
        state = "AGING"
    else:
        state = "STALE"
    diagnostic_stale = state == "STALE"
    enforced_stale = bool(configured_ttl is not None and configured_ttl > 0 and age is not None and age > configured_ttl)
    return {"capability_generated_at": capability.get("generated_at"), "capability_age_seconds": round(age, 3) if age is not None else None,
            "capability_freshness_state": state, "capability_stale": diagnostic_stale,
            "capability_enforced_stale": enforced_stale,
            "capability_ttl_seconds": configured_ttl if configured_ttl and configured_ttl > 0 else None}


def _lineage_readiness(open_positions: list[dict[str, Any]], lifecycle_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate current broker-linked exposure from historical diagnostics."""
    active_verified = active_unverified = legacy_unverified = historical_unverified = 0
    active_ids: set[str] = set()
    for row in open_positions:
        asset = _text(row.get("asset_class") or row.get("asset_type")).lower()
        if asset not in {"crypto", "cryptocurrency"}:
            continue
        identity = _text(row.get("position_id") or row.get("lifecycle_id") or row.get("entry_order_id") or row.get("symbol"))
        if identity:
            active_ids.add(identity)
        linked = bool(row.get("entry_order_id") or row.get("source_broker_order_id") or row.get("entry_fill_id") or row.get("source_client_order_id"))
        if bool(row.get("entry_price_verified")):
            active_verified += 1
        elif linked:
            active_unverified += 1
        else:
            legacy_unverified += 1
    for row in lifecycle_rows:
        asset = _text(row.get("asset_class") or row.get("asset_type")).lower()
        if asset not in {"crypto", "cryptocurrency"} or bool(row.get("entry_price_verified")):
            continue
        identity = _text(row.get("position_id") or row.get("lifecycle_id") or row.get("entry_order_id") or row.get("symbol"))
        if identity and identity in active_ids:
            continue
        if bool(row.get("closed")) or _text(row.get("exit_timestamp")):
            historical_unverified += 1
        else:
            legacy_unverified += 1
    return {
        "active_verified_entries": active_verified,
        "active_unverified_entries": active_unverified,
        "legacy_unverified_entries": legacy_unverified,
        "historical_unverified_entries": historical_unverified,
        "active_lineage_blocking": bool(active_unverified),
        "unverified_entries_diagnostic_only": True,
        "official_metrics_require_verified_entry": True,
    }


def _safety() -> dict[str, Any]:
    return {
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "broker_live_endpoint_allowed": False,
        "crypto_live_trading_enabled": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "ranking_behavior_changed": False,
        "thresholds_changed": False,
        "position_sizing_changed": False,
        "automatic_promotions_enabled": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "learned_exits_enabled": False,
        "behavior_safe_to_apply": False,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }


def _data_state(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not rows:
        return "DATA_UNAVAILABLE", ["no_cached_crypto_candidate_quote"]
    reasons: list[str] = []
    for row in rows:
        gate = dict(row.get("gate_status") or {})
        failures = [str(gate.get(key) or "") for key in ("timestamp_freshness", "data_quality")]
        if all(value == "PASS" for value in failures):
            return "DATA_READY", []
        reasons.extend(value for value in failures if value and value != "PASS")
    if any("STALE" in reason for reason in reasons):
        return "DATA_STALE", sorted(set(reasons))
    return "DATA_DEGRADED", sorted(set(reasons))


def _liquidity_state(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not rows:
        return "LIQUIDITY_NOT_READY", ["no_cached_crypto_liquidity_observation"]
    reasons: list[str] = []
    for row in rows:
        gate = dict(row.get("gate_status") or {})
        failures = [str(gate.get(key) or "") for key in ("quote_spread", "volume_liquidity", "order_schema_min_notional")]
        if all(value == "PASS" for value in failures):
            return "LIQUIDITY_READY", []
        reasons.extend(value for value in failures if value and value != "PASS")
    return "LIQUIDITY_NOT_READY", sorted(set(reasons))


def build_crypto_operational_integrity_readiness_v1(
    *,
    lane: dict[str, Any] | None = None,
    capability: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    open_positions: list[dict[str, Any]] | None = None,
    pending_orders: list[dict[str, Any]] | None = None,
    lifecycle_rows: list[dict[str, Any]] | None = None,
    buying_power: Any = None,
    known_equity_symbols: set[str] | None = None,
) -> dict[str, Any]:
    """Build a fail-closed crypto readiness summary from already cached facts."""
    lane = dict(lane or {})
    capability = dict(capability or {})
    candidates = [dict(row) for row in (candidates or []) if isinstance(row, dict)][:50]
    open_positions = [dict(row) for row in (open_positions or []) if isinstance(row, dict)][:200]
    pending_orders = [dict(row) for row in (pending_orders or []) if isinstance(row, dict)][:200]
    lifecycle_rows = [dict(row) for row in (lifecycle_rows or []) if isinstance(row, dict)][:1200]
    supported = {str(item or "").upper().replace("-", "/") for item in (capability.get("supported_pairs") or [])}
    tradable = {str(item or "").upper().replace("-", "/") for item in (capability.get("tradable_pairs") or [])}
    asset_rules = dict(capability.get("asset_rules") or {})
    paper_mode = bool(capability.get("paper_mode_verified") or lane.get("paper_mode_verified"))
    live_endpoint = bool(capability.get("live_endpoint_detected"))
    kill_switch = bool(lane.get("kill_switch_enabled"))
    capital_configured = bool(lane.get("capital_configured"))
    capital_limit = lane.get("capital_limit")
    capability_freshness = _capability_freshness(capability)
    normalized_open = {
        normalize_crypto_pair_strict(row.get("symbol"), asset_class=row.get("asset_class") or row.get("asset_type") or "crypto").get("normalized_symbol")
        for row in open_positions
        if str(row.get("asset_class") or row.get("asset_type") or "").lower() in {"crypto", "cryptocurrency"}
    }
    normalized_pending = {
        normalize_crypto_pair_strict(row.get("symbol"), asset_class=row.get("asset_class") or row.get("asset_type") or "crypto").get("normalized_symbol")
        for row in pending_orders
        if str(row.get("asset_class") or row.get("asset_type") or "").lower() in {"crypto", "cryptocurrency"}
        and str(row.get("status") or "").lower() in {"new", "accepted", "pending_new", "partially_filled", "held"}
    }
    normalized_open.discard(None)
    normalized_open.discard("")
    normalized_pending.discard(None)
    normalized_pending.discard("")
    evaluated: list[dict[str, Any]] = []
    for raw in candidates:
        identity = normalize_crypto_pair_strict(
            raw.get("symbol") or raw.get("ticker"),
            asset_class=raw.get("asset_class") or raw.get("asset_type"),
            known_equity_symbols=known_equity_symbols or set(),
            base_symbol=raw.get("base_symbol"), quote_currency=raw.get("quote_currency"),
        )
        pair = identity.get("normalized_symbol")
        duplicate = bool(pair and (pair in normalized_open or pair in normalized_pending))
        integrity = candidate_execution_integrity(
            raw, supported_pairs=supported, tradable_pairs=tradable,
            known_equity_symbols=known_equity_symbols or set(),
            lane_state=str(lane.get("lane_state") or "LANE_BLOCKED"),
            paper_mode_verified=paper_mode, live_endpoint_detected=live_endpoint,
            capacity_fact=dict(lane.get("canonical_capacity_fact") or {}),
            duplicate_pending=duplicate, broker_reconciliation_ok=bool(lane.get("broker_reconciliation_ok", False)),
            kill_switch_enabled=kill_switch,
        )
        evaluated.append({
            "candidate_id": raw.get("candidate_id"), "symbol": pair or raw.get("symbol"),
            "asset_class": "crypto", "asset_type": "crypto", "lane_id": "CRYPTO",
            "pair_eligibility": "TRADABLE" if pair in tradable else "UNSUPPORTED_OR_UNTRADABLE",
            "duplicate_position": bool(pair and pair in normalized_open),
            "duplicate_pending_order": bool(pair and pair in normalized_pending),
            "asset_rule": dict(asset_rules.get(pair) or {}) if pair else {},
            "quote_timestamp": raw.get("quote_timestamp"),
            "provider_quote_timestamp": raw.get("provider_quote_timestamp") or raw.get("quote_timestamp"),
            "quote_source": raw.get("quote_source") or raw.get("crypto_quote_evidence_source"),
            **integrity,
        })
    data_status, data_reasons = _data_state(evaluated)
    liquidity_status, liquidity_reasons = _liquidity_state(evaluated)
    execution_ready = [row for row in evaluated if bool(row.get("execution_eligible"))]
    # Preserve candidate/gate order.  Sorting all failures loses the one
    # causal failure that explains why a particular candidate cannot advance.
    first_causal_blockers = [
        {"symbol": row.get("symbol"), **dict(row.get("first_causal_blocker") or {})}
        for row in evaluated if isinstance(row.get("first_causal_blocker"), dict)
    ]
    execution_blockers = list(dict.fromkeys(
        str(row.get("gate") or "") for row in first_causal_blockers if str(row.get("gate") or "")
    ))
    lineage = _lineage_readiness(open_positions, lifecycle_rows)
    exact_blockers: list[str] = []
    if not capital_configured:
        exact_blockers.append("CRYPTO_PAPER_CAPITAL_NOT_CONFIGURED")
    if not paper_mode or live_endpoint or not bool(capability.get("crypto_trading_supported")) or capability_freshness["capability_enforced_stale"]:
        exact_blockers.append("CRYPTO_CAPABILITY_CACHE_STALE" if capability_freshness["capability_enforced_stale"] else str(capability.get("exact_blocker") or "CRYPTO_BROKER_NOT_READY"))
    if kill_switch:
        exact_blockers.append("CRYPTO_PAPER_KILL_SWITCH_ENABLED")
    if data_status != "DATA_READY":
        exact_blockers.extend(data_reasons[:3])
    if liquidity_status != "LIQUIDITY_READY":
        exact_blockers.extend(liquidity_reasons[:3])
    if evaluated and not execution_ready:
        exact_blockers.extend(
            f"CRYPTO_CANDIDATE_GATE_FAILED:{row.get('symbol')}:{row.get('gate')}"
            for row in first_causal_blockers[:3]
        )
    if lineage["active_lineage_blocking"]:
        exact_blockers.append("CRYPTO_ENTRY_LINEAGE_UNVERIFIED")
    if not capital_configured:
        status = "NOT_CONFIGURED"
    elif not paper_mode or live_endpoint or not bool(capability.get("crypto_trading_supported")) or capability_freshness["capability_enforced_stale"]:
        status = "BROKER_NOT_READY"
    elif not bool(lane.get("activation_requested")) or kill_switch:
        status = "PAPER_READY_BLOCKED_BY_HUMAN_CONFIGURATION"
    elif data_status != "DATA_READY":
        status = "DATA_NOT_READY"
    elif liquidity_status != "LIQUIDITY_READY":
        status = "LIQUIDITY_NOT_READY"
    elif lineage["active_lineage_blocking"]:
        status = "LINEAGE_NOT_READY"
    elif not evaluated:
        status = "EVIDENCE_NOT_READY"
    elif not execution_ready:
        # A data-complete candidate is not execution-ready until every
        # canonical candidate gate passes. This is a reporting correction;
        # candidate_execution_integrity remains the gate owner.
        status = "EVIDENCE_NOT_READY"
    else:
        status = "PAPER_READY"
    return {
        "suite": "Crypto Operational Integrity & Readiness V1", "version": VERSION,
        "status": status, "generated_at": _now_iso(), "get_route_read_only": True,
        "crypto_lane_enabled": bool(lane.get("paper_crypto_enabled")),
        # An existing human configuration is not an authorization when this
        # diagnostic finds a current integrity blocker.
        "paper_execution_currently_allowed": bool(lane.get("paper_crypto_enabled")) and status == "PAPER_READY",
        "execution_ready_candidate_count": len(execution_ready),
        "candidate_execution_blockers": execution_blockers[:12],
        "candidate_first_causal_blockers": first_causal_blockers[:25],
        "human_configuration_required": not bool(lane.get("activation_requested")) or not capital_configured,
        "capital_readiness": {
            "configured": capital_configured, "configured_capital": capital_limit,
            "configured_max_concurrent_positions": int(_num(lane.get("crypto_day_trade_capacity"), 0) + _num(lane.get("crypto_short_swing_capacity"), 0)),
            "configured_per_trade_cap": None, "available_paper_buying_power": _num(buying_power, 0.0) if buying_power not in (None, "") else None,
            "human_provided": capital_configured, "blocker": "" if capital_configured else "CRYPTO_PAPER_CAPITAL_NOT_CONFIGURED",
        },
        "reconciliation": {
            "broker_reconciliation_status": lane.get("broker_reconciliation_status") or "UNAVAILABLE",
            "canonical_local_position_source": lane.get("canonical_local_position_source"),
            "canonical_local_position_query_scope": lane.get("canonical_local_position_query_scope"),
            "canonical_local_open_crypto_count": int(_num(lane.get("canonical_local_open_crypto_count"), 0)),
            "noncanonical_rows_observed": lane.get("noncanonical_rows_observed"),
            "noncanonical_rows_excluded": lane.get("noncanonical_rows_excluded"),
            "local_crypto_open_count": int(_num(lane.get("local_crypto_open_count"), 0)),
            "broker_crypto_open_count": lane.get("broker_crypto_open_count"),
            "matched_crypto_position_count": int(_num(lane.get("matched_crypto_position_count"), 0)),
            "local_only_crypto_position_count": int(_num(lane.get("local_only_crypto_position_count"), 0)),
            "broker_only_crypto_position_count": lane.get("broker_only_crypto_position_count"),
            "pending_crypto_order_count": int(_num(lane.get("pending_crypto_order_count"), len(normalized_pending))),
            "buying_power_available": bool(lane.get("buying_power_available", buying_power is not None)),
            "buying_power_source": lane.get("buying_power_source") or "unavailable",
            "historical_rows_excluded": lane.get("historical_rows_excluded"),
            "diagnostic_rows_excluded": lane.get("diagnostic_rows_excluded"),
            "reconstructed_rows_excluded": lane.get("reconstructed_rows_excluded"),
            "closed_rows_excluded": lane.get("closed_rows_excluded"),
            "unfilled_rows_excluded": lane.get("unfilled_rows_excluded"),
        },
        "broker_capability": {"paper_mode_verified": paper_mode, "live_endpoint_detected": live_endpoint,
            "crypto_trading_supported": bool(capability.get("crypto_trading_supported")), "supported_pairs": sorted(supported)[:80],
            "tradable_pairs": sorted(tradable)[:80], "supported_order_types": capability.get("supported_order_types") or [],
            "supported_time_in_force": capability.get("supported_time_in_force") or [], "fractional_quantity_supported": bool(capability.get("fractional_quantity_supported")),
            "market_data_entitlement_confirmed": bool(capability.get("market_data_entitlement_confirmed")),
            "market_data_status": capability.get("market_data_status") or "UNKNOWN", "supported_pairs_count": len(supported), "tradable_pairs_count": len(tradable)},
        "pair_eligibility": {"evaluated_candidates": evaluated[:25], "first_causal_blockers": first_causal_blockers[:25], "supported_pairs_count": len(supported), "tradable_pairs_count": len(tradable),
            "canonical_pair_capability": {pair: {"supported": pair in supported, "tradable": pair in tradable,
                "pair_eligibility": "TRADABLE" if pair in tradable else "SUPPORTED_NOT_TRADABLE" if pair in supported else "UNSUPPORTED_OR_UNTRADABLE",
                "asset_rule": dict(asset_rules.get(pair) or {})} for pair in ("LINK/USD", "LTC/USD")}},
        "data_readiness": {"status": data_status, "reasons": data_reasons, "evaluated_candidates": len(evaluated)},
        "liquidity_readiness": {"status": liquidity_status, "reasons": liquidity_reasons},
        "duplicate_exposure": {"open_crypto_symbols": sorted(normalized_open), "pending_crypto_symbols": sorted(normalized_pending),
            "duplicate_candidate_count": sum(1 for row in evaluated if row.get("duplicate_position") or row.get("duplicate_pending_order"))},
        "capability_source": capability.get("source") or "unknown_fail_closed", "capability_cache_only": bool(capability.get("cache_only")),
        **capability_freshness,
        "lifecycle_lineage": {"verified_open_entries": lineage["active_verified_entries"], "unverified_open_entries": lineage["active_unverified_entries"], **lineage},
        "lineage_readiness": lineage,
        "evidence_isolation": {"asset_class": "crypto", "equity_evidence_consumed": False, "crypto_thresholds_separate": True,
            "required_partition_keys": ["asset_class", "lane_id", "strategy_cohort", "horizon", "symbol", "regime", "lifecycle_stage"]},
        "exact_blockers": sorted(set(filter(None, exact_blockers))),
        "warnings": [warning for warning in [
            "crypto_capability_snapshot_stale_diagnostic_only"
            if capability_freshness["capability_stale"] and not capability_freshness["capability_enforced_stale"] else "",
        ] if warning],
        "recommended_human_actions": ["Configure a separate crypto paper capital limit only if human-approved"] if not capital_configured else [],
        **_safety(),
    }


class CryptoOperationalIntegrityReadinessV1:
    """Small state owner; only worker code should call ``write_snapshot``."""

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = str(state_dir or "state")
        self.path = os.path.join(self.state_dir, "crypto_operational_integrity_readiness_v1.json")

    def load_snapshot(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}

    def build(self, **kwargs: Any) -> dict[str, Any]:
        return build_crypto_operational_integrity_readiness_v1(**kwargs)

    def write_snapshot(self, payload: dict[str, Any]) -> None:
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            temp = f"{self.path}.tmp"
            with open(temp, "w", encoding="utf-8") as handle:
                json.dump(dict(payload or {}), handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
            os.replace(temp, self.path)
        except Exception:
            return
