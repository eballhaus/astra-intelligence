"""Canonical read-only lifecycle decisions built from existing position evidence.

This module never submits or queues an exit. PaperAutopilot remains the sole
authorized order writer; this owner only makes every position's evidence,
cohort, lifecycle classification, and policy blocker explicit.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence


_LEGACY_SWING_CANARY_CONTROL_PATH = os.path.join("state", "legacy_swing_canary_control_v1.json")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _num(value: Any) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    value = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def _legacy_swing_canary_control_v1() -> dict[str, Any]:
    """Read an explicit local control record; malformed state always fails closed."""
    try:
        with open(_LEGACY_SWING_CANARY_CONTROL_PATH, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return dict(payload) if isinstance(payload, dict) else {}
    except Exception:
        return {}


def set_legacy_swing_canary_control_v1(*, enabled: bool, kill_switch: bool, readiness_state: str) -> dict[str, Any]:
    """Persist a human-authorized control only after the read-only readiness gate."""
    ready = str(readiness_state or "").upper() in {"READY", "READY_WITH_BACKLOG"}
    if enabled and (kill_switch or not ready):
        raise ValueError("legacy_swing_canary_activation_requires_ready_state_and_clear_kill_switch")
    payload = {
        "schema_version": "legacy_swing_canary_control_v1",
        "activation_state": "ACTIVATED_AFTER_READINESS_V1" if enabled and not kill_switch else "DISABLED_FAIL_CLOSED",
        "enabled": bool(enabled), "kill_switch": bool(kill_switch),
        "readiness_state": str(readiness_state or ""), "updated_at": _iso(),
    }
    os.makedirs(os.path.dirname(_LEGACY_SWING_CANARY_CONTROL_PATH) or ".", exist_ok=True)
    temporary = _LEGACY_SWING_CANARY_CONTROL_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
    os.replace(temporary, _LEGACY_SWING_CANARY_CONTROL_PATH)
    return payload


def legacy_swing_canary_configuration_v1(control: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Canonical paper-only canary configuration with a fail-closed control record."""
    runtime_control = dict(control) if control is not None else _legacy_swing_canary_control_v1()
    active = bool(runtime_control.get("enabled")) and not bool(runtime_control.get("kill_switch")) and runtime_control.get("activation_state") == "ACTIVATED_AFTER_READINESS_V1"
    return {
        "policy_id": "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1",
        "enabled": active,
        "kill_switch": not active,
        "paper_only": True,
        "max_active_exit_orders": 1,
        "max_exit_submissions_per_cycle": 1,
        "max_exit_submissions_per_day": 1,
        "max_canary_notional_usd": 100.0,
        "max_legacy_book_percentage_per_cycle": 0.02,
        "minimum_decision_confidence": 0.80,
        "minimum_direct_confirmation_confidence": 0.80,
        "rejection_limit": 2,
        "fail_closed_after_rejections": True,
        "cooldown_after_action": "one_trading_day",
        "require_fresh_quote": True,
        "require_acceptable_spread": True,
        "require_liquidity": True,
        "require_governance_pass": True,
        "require_complete_lineage": True,
        "require_reconciled_quantity": True,
        "require_idempotency": True,
        "disable_on_governance_high_or_critical": True,
        "allow_replacement_before_exit_fill": False,
        "allow_shadow_only_action": False,
        "allow_conflicting_evidence_action": False,
        "allow_exit_review_alone": False,
        "eligible_classifications": [
            "THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "PROTECT_PROFIT",
            "PROTECT_PARTIAL", "REDUCE_RISK", "REPLACE_CANDIDATE",
        ],
        "advisory_classifications": [
            "HOLD_AS_PLANNED", "HOLD_WITH_WATCH", "EXIT_REVIEW",
            "INSUFFICIENT_EVIDENCE", "CONFLICTING_EVIDENCE", "LOW_CONFIDENCE",
        ],
        "activation_control_state": runtime_control.get("activation_state") or "DISABLED_FAIL_CLOSED",
        "activation_readiness_state": runtime_control.get("readiness_state") or "NOT_READY",
    }


def build_legacy_swing_direct_confirmation_v1(
    position: Mapping[str, Any],
    lifecycle_decision: Mapping[str, Any],
    required_evidence: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build direct, current, position-specific confirmation without inferred thesis evidence."""
    row, decision, evidence = dict(position or {}), dict(lifecycle_decision or {}), dict(required_evidence or {})
    position_id = _text(decision.get("position_id") or row.get("position_id") or row.get("asset_id"))
    activation_id = _text((decision.get("forward_baseline") or {}).get("baseline_id") or row.get("activation_id"))
    classification = _text(decision.get("classification")).upper()
    momentum, thesis, liquidity = (dict(evidence.get("MOMENTUM") or {}), dict(evidence.get("THESIS_STATE") or {}), dict(evidence.get("LIQUIDITY") or {}))
    quote = dict(row.get("broker_quote_record") or {})
    coverage = dict(row.get("direct_evidence_coverage") or {})
    current = bool(coverage.get("required_evidence_complete")) if coverage else all(str(item.get("status") or "").upper() == "CURRENT" for item in (momentum, thesis, liquidity))
    quote_current = str(quote.get("freshness_state") or "").upper() == "CURRENT" and _num(quote.get("bid")) not in (None, 0.0) and _num(quote.get("ask")) not in (None, 0.0)
    conflict = bool(decision.get("evidence_conflicting") or row.get("direct_evidence_conflicting"))
    stale = bool(decision.get("evidence_stale")) or any(str(item.get("freshness") or item.get("freshness_state") or "").upper() == "STALE" for item in (momentum, thesis, liquidity))
    missing = list(decision.get("evidence_missing") or [])
    negative_momentum = str(momentum.get("short_term_direction") or "").upper() in {"NEGATIVE", "COLLAPSE", "DETERIORATING"}
    poor_liquidity = str(liquidity.get("liquidity_state") or "").upper() in {"POOR", "THIN", "DETERIORATING"}
    direct_invalidation = bool(row.get("direct_thesis_invalidation") or decision.get("direct_thesis_invalidation"))
    giveback = _num(row.get("profit_giveback_pct") or row.get("giveback")) or 0.0
    return_pct = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc")) or 0.0
    state, confidence, reason = "UNCONFIRMED", 0.0, "DIRECT_ACTION_EVIDENCE_NOT_YET_SUFFICIENT"
    if conflict:
        state, reason = "CONFLICTING", "CURRENT_DIRECT_EVIDENCE_CONFLICT"
    elif stale:
        state, reason = "STALE", "CURRENT_DIRECT_EVIDENCE_STALE"
    elif not current or not quote_current:
        state, reason = "INSUFFICIENT", "CURRENT_DIRECT_EVIDENCE_INCOMPLETE"
    elif classification == "THESIS_BROKEN" and direct_invalidation:
        state, confidence, reason = "CONFIRMED_INVALIDATION", 0.9, "DIRECT_THESIS_INVALIDATION_WITH_CURRENT_MARKET_EVIDENCE"
    elif classification in {"CONTROLLED_LOSS_ACCEPTABLE", "REDUCE_RISK"} and negative_momentum and poor_liquidity:
        state, confidence, reason = "CONFIRMED_RISK_REDUCTION", 0.85, "CURRENT_MOMENTUM_AND_LIQUIDITY_RISK_DIVERGENCE"
    elif classification in {"PROTECT_PROFIT", "PROTECT_PARTIAL"} and return_pct > 0 and giveback >= 2.0:
        state, confidence, reason = "CONFIRMED_PROFIT_PROTECTION", 0.85, "CURRENT_PROFIT_GIVEBACK_CONFIRMED"
    elif classification in {"HOLD_AS_PLANNED", "HOLD_WITH_WATCH"} and not negative_momentum and not poor_liquidity:
        state, confidence, reason = "CONFIRMED_SUPPORT", 0.8, "CURRENT_DIRECT_EVIDENCE_SUPPORTS_CONTINUATION"
    confirmation_id = f"legacy-confirmation:{activation_id or position_id}:{classification}:{str(quote.get('record_id') or quote.get('quote_timestamp') or 'none')}"
    return {
        "schema_version": "legacy_swing_direct_confirmation_v1", "confirmation_id": confirmation_id,
        "position_id": position_id, "activation_id": activation_id, "symbol": _text(decision.get("symbol") or row.get("symbol")).upper(),
        "asset_class": row.get("asset_class") or "equity", "lane": decision.get("lane") or "SWING", "as_of": _iso(now),
        "lifecycle_classification": classification, "classification_confidence": _num(decision.get("classification_confidence") or decision.get("forecast_confidence")) or 0.0,
        "confirmation_state": state, "confirmation_confidence": confidence, "confirmation_reason": reason,
        "direct_market_evidence": {"quote_current": quote_current, "momentum_negative": negative_momentum, "liquidity_poor": poor_liquidity},
        "direct_position_evidence": {"return_pct": return_pct, "giveback": giveback},
        "direct_lifecycle_evidence": {"classification": classification, "direct_thesis_invalidation": direct_invalidation},
        "supporting_context": [], "opposing_evidence": [], "missing_evidence": missing, "stale_evidence": stale,
        "conflicting_evidence": conflict, "quote_record_id": quote.get("record_id"), "bar_record_id": momentum.get("record_id"),
        "liquidity_record_id": liquidity.get("record_id"), "thesis_record_id": thesis.get("record_id"),
        "classification_record_id": activation_id, "freshness_state": "CURRENT" if current and quote_current else "STALE" if stale else "UNAVAILABLE",
        "quality_state": "PASS" if state.startswith("CONFIRMED") else state, "limitations": missing + list(coverage.get("missing_evidence") or []),
        "next_confirmation_at": _iso(datetime.now(timezone.utc) + timedelta(hours=1)), "retry_count": 0,
    }


def build_legacy_swing_direct_evidence_coverage_v1(position: Mapping[str, Any], baseline: Mapping[str, Any], evidence: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Canonical current-direct-evidence coverage; contextual evidence never counts as complete."""
    row, base, required = dict(position or {}), dict(baseline or {}), dict(evidence or {})
    states = {name: str(dict(required.get(name) or {}).get("status") or "MISSING").upper() for name in ("MOMENTUM", "THESIS_STATE", "LIQUIDITY")}
    quote = dict(row.get("broker_quote_record") or {})
    quote_current = str(quote.get("freshness_state") or "").upper() == "CURRENT" and _num(quote.get("bid")) not in (None, 0.0) and _num(quote.get("ask")) not in (None, 0.0)
    asset = dict(row.get("broker_asset_record") or {})
    tradable = str(asset.get("freshness_state") or "").upper() == "CURRENT" and bool(asset.get("tradable"))
    missing = [name for name, state in states.items() if state != "CURRENT"] + ([] if quote_current else ["QUOTE"]) + ([] if tradable else ["TRADABILITY"])
    stale = [name for name, item in required.items() if str(dict(item or {}).get("freshness") or "").upper() == "STALE"]
    complete = not missing and not stale
    position_id = _text(row.get("position_id") or row.get("asset_id") or base.get("position_id"))
    activation_id = _text(base.get("baseline_id") or row.get("activation_id"))
    return {"schema_version": "legacy_swing_direct_evidence_coverage_v1", "coverage_id": f"legacy-coverage:{activation_id or position_id}", "position_id": position_id, "activation_id": activation_id, "symbol": _text(row.get("symbol")).upper(), "as_of": _iso(now), "quote_state": "CURRENT" if quote_current else "MISSING", "bar_state": states["MOMENTUM"], "momentum_state": states["MOMENTUM"], "liquidity_state": states["LIQUIDITY"], "tradability_state": "CURRENT" if tradable else "MISSING", "thesis_state": states["THESIS_STATE"], "mfe_state": "CURRENT" if _num(row.get("mfe")) is not None else "INSUFFICIENT", "mae_state": "CURRENT" if _num(row.get("mae")) is not None else "INSUFFICIENT", "giveback_state": "CURRENT" if _num(row.get("profit_giveback_pct") or row.get("giveback")) is not None else "INSUFFICIENT", "return_per_day_state": "CURRENT" if _num(row.get("return_per_day")) is not None else "INSUFFICIENT", "position_age_state": "CURRENT" if _num(row.get("days_held")) is not None else "INSUFFICIENT", "required_evidence_complete": complete, "missing_evidence": missing, "stale_evidence": stale, "conflicting_evidence": [], "last_complete_at": _iso(now) if complete else None, "coverage_percentage": round((5 - len(missing)) / 5 * 100, 2), "next_refresh_at": _iso(datetime.now(timezone.utc) + timedelta(minutes=15 if not complete else 60)), "refresh_priority": 100 if not complete else 25}


def build_legacy_swing_forward_value_v1(position: Mapping[str, Any], decision: Mapping[str, Any], coverage: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    row, d, c = dict(position or {}), dict(decision or {}), dict(coverage or {})
    ret, rpd = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc")), _num(row.get("return_per_day"))
    state = "INSUFFICIENT_FORWARD_EVIDENCE" if not c.get("required_evidence_complete") else "REDUCE_FORWARD_VALUE" if str(d.get("classification") or "") == "REDUCE_RISK" else "WATCH_FORWARD_VALUE" if str(d.get("classification") or "") == "HOLD_WITH_WATCH" else "HOLD_FORWARD_VALUE"
    return {"forward_value_id": f"legacy-forward-value:{c.get('activation_id')}", "position_id": c.get("position_id"), "activation_id": c.get("activation_id"), "symbol": c.get("symbol"), "as_of": _iso(now), "classification": d.get("classification"), "current_position_value": _num(row.get("market_value")), "current_unrealized_return": ret, "position_age": _num(row.get("days_held")), "hold_duration": _num(row.get("days_held")), "return_per_day": rpd, "momentum_state": row.get("momentum_state"), "thesis_state": row.get("thesis_state"), "liquidity_state": row.get("liquidity_state"), "MFE": _num(row.get("mfe")), "MAE": _num(row.get("mae")), "peak_unrealized": _num(row.get("peak_unrealized")), "giveback": _num(row.get("profit_giveback_pct") or row.get("giveback")), "forward_value_state": state, "forward_value_score": ret or 0.0, "forward_value_confidence": 0.8 if c.get("required_evidence_complete") else 0.0, "supporting_evidence": [], "opposing_evidence": [], "limitations": c.get("missing_evidence") or [], "next_review_at": c.get("next_refresh_at")}


def build_legacy_swing_opportunity_cost_v1(coverage: Mapping[str, Any], forward_value: Mapping[str, Any], context: Mapping[str, Any] | None = None, *, now: datetime | None = None) -> dict[str, Any]:
    c, f, ctx = dict(coverage or {}), dict(forward_value or {}), dict(context or {})
    alternative = dict(ctx.get("replacement_analysis") or {})
    qualified = bool(alternative.get("qualified"))
    state = "INSUFFICIENT_EVIDENCE" if not c.get("required_evidence_complete") else "REPLACE_CANDIDATE" if qualified and _num(alternative.get("expected_advantage")) and _num(alternative.get("expected_advantage")) > 0 else "NO_QUALIFIED_ALTERNATIVE"
    return {"opportunity_cost_id": f"legacy-opportunity:{c.get('activation_id')}", "position_id": c.get("position_id"), "activation_id": c.get("activation_id"), "symbol": c.get("symbol"), "as_of": _iso(now), "current_forward_value": f.get("forward_value_score"), "current_expected_return_per_day": f.get("return_per_day"), "alternative_available": qualified, "alternative_symbol_or_archetype": alternative.get("archetype"), "switching_advantage": alternative.get("expected_advantage"), "opportunity_cost_score": _num(alternative.get("expected_advantage")) or 0.0, "opportunity_cost_confidence": 0.5 if qualified else 0.0, "opportunity_cost_state": state, "limitations": f.get("limitations") or [], "advisory_only": True}


def build_legacy_swing_profit_capture_v1(position: Mapping[str, Any], coverage: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    row, c = dict(position or {}), dict(coverage or {})
    ret, peak, giveback = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc")) or 0.0, _num(row.get("peak_unrealized")) or 0.0, _num(row.get("profit_giveback_pct") or row.get("giveback")) or 0.0
    state = "INSUFFICIENT_EVIDENCE" if not c.get("required_evidence_complete") else "PROTECT_PROFIT" if peak > 0 and giveback >= 2 else "WATCH_GIVEBACK" if peak > 0 and giveback > 0 else "HEALTHY_CONTINUATION"
    return {"profit_capture_id": f"legacy-profit-capture:{c.get('activation_id')}", "position_id": c.get("position_id"), "activation_id": c.get("activation_id"), "symbol": c.get("symbol"), "as_of": _iso(now), "entry_price": _num(row.get("legacy_activation_price")), "current_price": _num(row.get("current_price") or row.get("market_price")), "current_unrealized_return": ret, "peak_unrealized_return": peak, "MFE": _num(row.get("mfe")), "MAE": _num(row.get("mae")), "giveback_percentage": giveback, "profit_capture_percentage": max(0.0, peak - giveback), "profit_capture_state": state, "protection_urgency": "HIGH" if state == "PROTECT_PROFIT" else "LOW", "confidence": 0.8 if c.get("required_evidence_complete") else 0.0, "supporting_evidence": [], "limitations": c.get("missing_evidence") or []}


def evaluate_legacy_swing_canary_eligibility_v1(position: Mapping[str, Any], decision: Mapping[str, Any], configuration: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate execution-independent requirements; disabled state never skips gates."""
    row, d, cfg = dict(position or {}), dict(decision or {}), dict(configuration or {})
    confidence = float(d.get("forecast_confidence") or 0.0)
    direct = bool(d.get("current_direct_confirmation"))
    direct_confidence = float(d.get("direct_confirmation_confidence") or (confidence if direct else 0.0))
    classification = str(d.get("classification") or "")
    evidence = dict(d.get("required_evidence") or {})
    momentum, thesis, liquidity_evidence = (dict(evidence.get("MOMENTUM") or {}), dict(evidence.get("THESIS_STATE") or {}), dict(evidence.get("LIQUIDITY") or {}))
    quote, asset = dict(row.get("broker_quote_record") or {}), dict(row.get("broker_asset_record") or {})
    quote_current = str(quote.get("response_state") or "").upper() == "SUCCESS" and str(quote.get("freshness_state") or "").upper() == "CURRENT"
    asset_current = str(asset.get("response_state") or "").upper() == "SUCCESS" and str(asset.get("freshness_state") or "").upper() == "CURRENT"
    bid, ask = _num(quote.get("bid")), _num(quote.get("ask"))
    fresh_quote = quote_current and bid is not None and ask is not None and bid > 0 and ask >= bid
    spread_ok = fresh_quote and ((ask - bid) / max((ask + bid) / 2.0, 1e-9) * 100.0) <= 1.0
    current_momentum = str(momentum.get("status") or "").upper() == "CURRENT"
    current_thesis = str(thesis.get("status") or "").upper() == "CURRENT"
    current_liquidity = str(liquidity_evidence.get("status") or "").upper() == "CURRENT" and str(liquidity_evidence.get("liquidity_state") or "").upper() == "ACCEPTABLE"
    checks: dict[str, bool] = {
        "persisted_activation": bool(d.get("forward_baseline", {}).get("legacy_activation_timestamp")),
        "active_shadow_twin": d.get("shadow_twin", {}).get("state") == "POSITION_SHADOW_TWIN_ACTIVE",
        "provisional_horizon": bool(d.get("provisional_horizon", {}).get("provisional_horizon")),
        "eligible_classification": classification in set(cfg.get("eligible_classifications") or ()),
        "decision_confidence": confidence >= float(cfg.get("minimum_decision_confidence") or 0.8),
        "direct_confirmation": direct,
        "direct_confirmation_confidence": direct_confidence >= float(cfg.get("minimum_direct_confirmation_confidence") or 0.8),
        "current_momentum": current_momentum,
        "current_thesis": current_thesis,
        "current_liquidity": current_liquidity,
        "fresh_quote": fresh_quote,
        "acceptable_spread": spread_ok,
        "liquidity": current_liquidity and asset_current and bool(asset.get("tradable")),
        "reconciled_quantity": bool(row.get("qty_available") or row.get("qty") or row.get("quantity")),
        "complete_lineage": bool(d.get("position_id") and d.get("forward_baseline", {}).get("baseline_id")),
        "governance_pass": not bool(row.get("governance_high_or_critical") or row.get("governance_blocked")),
        "paper_mode": bool(row.get("paper_mode_verified", True)),
        "live_endpoint_prohibited": not bool(row.get("live_endpoint_allowed", False)),
        "no_duplicate_pending_exit": not bool(row.get("duplicate_pending_exit") or row.get("pending_exit")),
        "idempotency": bool(d.get("position_id") and classification),
    }
    names = {
        "persisted_activation": "PERSISTED_ACTIVATION_REQUIRED", "active_shadow_twin": "ACTIVE_SHADOW_TWIN_REQUIRED",
        "provisional_horizon": "PROVISIONAL_HORIZON_REQUIRED", "eligible_classification": "ADVISORY_CLASSIFICATION",
        "decision_confidence": "DECISION_CONFIDENCE_BELOW_MINIMUM", "direct_confirmation": "DIRECT_CONFIRMATION_REQUIRED",
        "direct_confirmation_confidence": "DIRECT_CONFIRMATION_CONFIDENCE_BELOW_MINIMUM", "current_momentum": "CURRENT_MOMENTUM_REQUIRED",
        "current_thesis": "CURRENT_THESIS_REQUIRED", "current_liquidity": "CURRENT_LIQUIDITY_REQUIRED", "fresh_quote": "FRESH_QUOTE_REQUIRED",
        "acceptable_spread": "ACCEPTABLE_SPREAD_REQUIRED", "liquidity": "LIQUIDITY_REQUIRED",
        "reconciled_quantity": "RECONCILED_QUANTITY_REQUIRED", "complete_lineage": "COMPLETE_LINEAGE_REQUIRED",
        "governance_pass": "GOVERNANCE_PASS_REQUIRED", "paper_mode": "PAPER_MODE_REQUIRED",
        "live_endpoint_prohibited": "LIVE_ENDPOINT_PROHIBITED", "no_duplicate_pending_exit": "DUPLICATE_PENDING_EXIT",
        "idempotency": "IDEMPOTENCY_REQUIRED",
    }
    failures = [names[key] for key, passed in checks.items() if not passed]
    position_id = str(d.get("position_id") or row.get("asset_id") or row.get("symbol") or "")
    action_id = f"legacy-canary:{position_id}:{classification}"
    quantity = _num(row.get("qty") or row.get("quantity")) or 0.0
    price = _num(row.get("current_price") or row.get("market_price")) or 0.0
    legacy_book_notional = _num(row.get("legacy_book_notional")) or 0.0
    notional_cap = min(float(cfg.get("max_canary_notional_usd") or 0.0), legacy_book_notional * float(cfg.get("max_legacy_book_percentage_per_cycle") or 0.0))
    proposed = min(quantity, notional_cap / price) if price > 0 and notional_cap > 0 else 0.0
    if proposed <= 0:
        failures.append("CANARY_NOTIONAL_OR_LEGACY_BOOK_REQUIRED")
    return {
        "technical_eligibility": not failures,
        "eligibility_checks": checks,
        "eligibility_failures": failures,
        "exact_blocker": failures[0] if failures else None,
        "action_id": action_id,
        "client_order_id": action_id[:48],
        "idempotency_key": action_id,
        "proposed_quantity": proposed,
        "proposed_notional": round(proposed * price, 6),
        "decision_confidence": confidence,
        "direct_confirmation_confidence": direct_confidence,
        "execution_authorized": bool(not failures and cfg.get("enabled") and not cfg.get("kill_switch")),
        "final_state": "KILL_SWITCH_ACTIVE" if cfg.get("kill_switch") else "CANARY_DISABLED" if not cfg.get("enabled") else "TECHNICALLY_ELIGIBLE",
    }


def select_legacy_swing_canary_candidate_v1(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    eligible = [dict(row) for row in rows if row.get("technical_eligibility")]
    for row in eligible:
        decision = dict(row.get("decision") or {})
        eligibility = dict(row.get("eligibility") or row)
        components = {
            "decision_confidence": float(eligibility.get("decision_confidence") or decision.get("forecast_confidence") or 0.0),
            "direct_deterioration": float(decision.get("direct_deterioration_strength") or 0.0),
            "avoided_loss": float(decision.get("expected_avoided_loss") or 0.0),
            "forward_value_disadvantage": max(0.0, float(decision.get("exit_now_forward_value") or 0.0) - float(decision.get("hold_forward_value") or 0.0)),
            "opportunity_cost": float(decision.get("opportunity_cost") or 0.0),
            "liquidity_quality": 1.0 if eligibility.get("eligibility_checks", {}).get("liquidity", True) else 0.0,
            "evidence_conflict": 1.0 if decision.get("consensus_state") == "CONFLICTING_EVIDENCE" else 0.0,
            "execution_risk": 0.0,
        }
        row["score_components"] = components
        row["candidate_score"] = round(
            components["decision_confidence"] + components["direct_deterioration"] + components["avoided_loss"]
            + components["forward_value_disadvantage"] + components["opportunity_cost"] + components["liquidity_quality"]
            - components["evidence_conflict"] - components["execution_risk"], 6,
        )
    ranked = sorted(eligible, key=lambda r: (-float(r.get("candidate_score") or 0.0), str(r.get("symbol") or ""), str(r.get("position_id") or "")))
    return {"technically_eligible_candidates": ranked, "selected_candidate": ranked[0] if ranked else None,
            "non_selected_candidates": ranked[1:], "tie_break_reason": "score_desc_symbol_position_asc", "selection_timestamp": _iso()}


def build_legacy_swing_canary_pre_submit_v1(
    *, position: Mapping[str, Any], lifecycle_decision: Mapping[str, Any],
    eligibility: Mapping[str, Any], selection: Mapping[str, Any],
    configuration: Mapping[str, Any], now: datetime | None = None,
) -> dict[str, Any] | None:
    """Build a broker-neutral handoff. This owner never calls an order writer."""
    row, decision, gate, selected, cfg = (dict(position or {}), dict(lifecycle_decision or {}),
                                           dict(eligibility or {}), dict(selection or {}), dict(configuration or {}))
    chosen = dict(selected.get("selected_candidate") or {})
    position_id = str(decision.get("position_id") or row.get("asset_id") or row.get("symbol") or "")
    if not gate.get("technical_eligibility") or str(chosen.get("position_id") or "") != position_id:
        return None
    price = _num(row.get("current_price") or row.get("market_price")) or 0.0
    quantity = _num(gate.get("proposed_quantity")) or 0.0
    return {
        "schema_version": "legacy_swing_canary_pre_submit_v1",
        "pre_submit_state": "LEGACY_SWING_CANARY_PRE_SUBMIT_READY",
        "policy_id": cfg.get("policy_id"), "pre_submit_id": f"pre-submit:{gate.get('action_id')}", "created_at": _iso(now),
        "position_id": position_id, "activation_id": decision.get("forward_baseline", {}).get("baseline_id"),
        "symbol": decision.get("symbol") or row.get("symbol"), "asset_class": row.get("asset_class") or row.get("asset_type"),
        "lane": decision.get("lane"), "cohort": decision.get("cohort"),
        "provisional_horizon": decision.get("provisional_horizon", {}).get("provisional_horizon"),
        "classification": decision.get("classification"), "decision_confidence": gate.get("decision_confidence"),
        "direct_confirmation_state": decision.get("current_direct_confirmation"),
        "direct_confirmation_confidence": gate.get("direct_confirmation_confidence"),
        "quote_timestamp": row.get("quote_timestamp") or row.get("updated_at"), "quote_price": price,
        "bid": row.get("bid"), "ask": row.get("ask"), "spread": row.get("spread"),
        "liquidity_state": "ACCEPTABLE", "quantity_available": row.get("qty") or row.get("quantity"),
        "proposed_quantity": quantity, "proposed_notional": gate.get("proposed_notional"),
        "normalized_quantity_preview": quantity, "action_id": gate.get("action_id"),
        "client_order_id": gate.get("client_order_id"), "idempotency_key": gate.get("idempotency_key"),
        "governance_state": "PASS", "lineage_state": "COMPLETE", "technical_eligibility": True,
        "candidate_score": chosen.get("candidate_score"), "selected_state": "SELECTED",
        "canary_enabled": bool(cfg.get("enabled")), "kill_switch_state": bool(cfg.get("kill_switch")),
        "execution_authorized": bool(gate.get("execution_authorized")), "writer_contract_status": "ADAPTER_MAPPING_VALID",
        "writer_adapter_required": False, "blocker": None if gate.get("execution_authorized") else "CANARY_DISABLED",
        "limitations": [] if gate.get("execution_authorized") else ["canary_execution_not_authorized"], "evidence_sources": decision.get("evidence_rows") or [],
    }


def legacy_swing_writer_adapter_contract_v1() -> dict[str, Any]:
    """Machine-readable boundary for the canonical legacy SWING writer adapter."""
    return {
        "status": "WRITER_PATH_CONNECTED",
        "existing_policy_owner": "PaperAutopilot.authorized_lane_exit_pending",
        "existing_writer": "PaperAutopilot._submit_authorized_lane_exit",
        "existing_writer_inputs": ["open_row", "broker_position", "exit_reason"],
        "current_lane_assumption": "DAY/CRYPTO ownership is unchanged; the legacy SWING adapter is admitted only by the canary control and writer guard",
        "required_pre_submit_fields": ["position_id", "action_id", "client_order_id", "idempotency_key", "proposed_quantity", "proposed_notional", "classification", "lineage_state", "governance_state"],
        "required_validations": ["paper_mode", "live_endpoint_prohibited", "quote_spread_liquidity", "quantity_normalization", "duplicate_order", "idempotency", "canary_limits"],
        "swing_rejection_condition": "ordinary SWING rows without legacy_swing_canary_adapter_v1 remain lane_not_authorized_for_v2_exit",
        "smallest_adapter_boundary": "legacy_swing_canary_writer_pre_submit maps a canonical pre-submit object to the existing lane writer",
        "expected_return_states": ["ADAPTER_MAPPING_VALID", "WRITER_PATH_CONNECTED", "CANARY_DISABLED", "KILL_SWITCH_ACTIVE", "EXECUTION_NOT_AUTHORIZED", "BROKER_SUBMISSION_BLOCKED"],
        "future_adapter_tests": ["legacy_swing_pre_submit_contract", "disabled_no_broker_submission", "writer_quantity_idempotency", "active_canary_guard_fail_closed"],
    }


def build_legacy_forward_baseline_v1(position: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Describe forward-only evidence without inventing a legacy entry plan."""
    row = dict(position or {})
    cohort = classify_position_cohort_v1(row)
    meaningful = cohort["cohort"] not in {"DUST_POSITION", "BROKER_RESIDUE_POSITION"}
    activation = _text(row.get("legacy_activation_timestamp") or row.get("forward_activation_timestamp")) or None
    price = _num(row.get("current_price") or row.get("market_price"))
    ret = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc"))
    if ret is not None and abs(ret) <= 1:
        ret *= 100.0
    state = "NOT_APPLICABLE" if not meaningful else "LEGACY_FORWARD_BASELINE_COMPLETE" if activation and price is not None else "LEGACY_FORWARD_BASELINE_PARTIAL"
    return {
        "baseline_id": f"legacy-forward:{cohort['position_id']}", "baseline_state": state,
        "legacy_activation_timestamp": activation, "baseline_generated_at": _iso(now),
        "position_id": cohort["position_id"], "symbol": _text(row.get("symbol")).upper(),
        "activation_price": _num(row.get("legacy_activation_price")) or price,
        "activation_unrealized_return_pct": _num(row.get("legacy_activation_unrealized_return_pct")) if activation else ret,
        "original_horizon": "UNKNOWN", "original_thesis_state": "UNAVAILABLE",
        "current_lifecycle_stage": "POSITION_ACTIVE", "limitations": [] if state == "LEGACY_FORWARD_BASELINE_COMPLETE" else ["forward_activation_timestamp_not_yet_persisted_by_worker"],
        "evidence_class": "CURRENT_DIRECT_FORWARD_ONLY",
    }


def estimate_legacy_provisional_horizon_v1(position: Mapping[str, Any], baseline: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Estimate review cadence only; it never rewrites the unknown original horizon."""
    del now
    row = dict(position or {})
    age = _num(row.get("days_held") or row.get("position_age_days"))
    if age is None:
        group, confidence = "HORIZON_UNKNOWN", 0.0
    elif age <= 3:
        group, confidence = "SWING_1_3_DAYS", 0.35
    elif age <= 7:
        group, confidence = "SWING_4_7_DAYS", 0.45
    elif age <= 14:
        group, confidence = "SWING_1_2_WEEKS", 0.55
    else:
        group, confidence = "SWING_MULTI_WEEK", 0.60
    return {
        "original_horizon": "UNKNOWN", "provisional_horizon": group,
        "provisional_horizon_confidence": confidence,
        "provisional_horizon_sources": ["current_holding_age", "current_lane"] if age is not None else [],
        "provisional_horizon_activation_timestamp": baseline.get("legacy_activation_timestamp"),
        "recommended_review_cadence": "regular_swing_checkpoint" if group != "HORIZON_UNKNOWN" else "heightened_manual_review",
        "state": "HORIZON_EVIDENCE_INSUFFICIENT" if group == "HORIZON_UNKNOWN" else "PROVISIONAL_HORIZON_ACTIVE",
    }


def legacy_swing_horizon_daily_contract_v1(horizon: str) -> dict[str, Any]:
    """Conservative completed-session contracts for legacy daily context."""
    key = _text(horizon).upper() or "SWING_UNKNOWN_PROVISIONAL"
    contracts = {
        "SWING_1_TO_3_DAY": (8, 12, 16), "SWING_4_TO_7_DAY": (10, 15, 21),
        "SWING_1_TO_2_WEEK": (15, 22, 31), "SWING_MULTI_WEEK": (25, 35, 45),
        "SWING_UNKNOWN_PROVISIONAL": (15, 22, 31),
    }
    minimum, preferred, calendar_days = contracts.get(key, contracts["SWING_UNKNOWN_PROVISIONAL"])
    return {"contract_id": f"legacy-swing-daily:{key.lower()}", "lane": "SWING", "horizon": key,
            "preferred_timeframe": "1Hour", "fallback_timeframe": "1Day", "minimum_completed_bars": minimum,
            "preferred_completed_bars": preferred, "minimum_calendar_lookback_days": calendar_days,
            "maximum_latest_completed_bar_age": "market_calendar_aware", "session_scope": "DAILY_COMPLETED_BARS",
            "volume_requirement": "EXPLICIT_IF_AVAILABLE", "gap_tolerance": 2, "adjustment_requirement": "KNOWN_OR_UNKNOWN_EXPLICIT",
            "minimum_source_quality": "CURRENT_SUFFICIENT", "momentum_outputs_supported": ["MEDIUM_TERM_SWING_CONTEXT", "NO_INTRADAY_PRECISION"],
            "limitations": ["daily_context_cannot_claim_intraday_precision"]}


def build_legacy_swing_horizon_record_v1(position: Mapping[str, Any], baseline: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    provisional = estimate_legacy_provisional_horizon_v1(position, baseline, now=now)
    horizon = _text(provisional.get("provisional_horizon") or "SWING_UNKNOWN_PROVISIONAL").upper()
    state = "HORIZON_PROVISIONAL" if horizon else "HORIZON_INSUFFICIENT"
    position_id = _text(position.get("asset_id") or position.get("position_id") or baseline.get("baseline_id"))
    return {"schema_version": "legacy_swing_horizon_record_v1", "horizon_record_id": f"legacy-horizon:{position_id}",
            "position_id": position_id, "activation_id": baseline.get("baseline_id"), "symbol": _text(position.get("symbol")).upper(),
            "asset_class": "equity", "lane": "SWING", "strategy": baseline.get("strategy") or "LEGACY_SWING", "original_horizon": provisional.get("original_horizon") or "UNKNOWN",
            "provisional_horizon": horizon, "certified_horizon": None, "effective_horizon": horizon, "horizon_state": state,
            "horizon_confidence": provisional.get("provisional_horizon_confidence") or 0.0, "horizon_basis": provisional.get("provisional_horizon_sources") or [],
            "supporting_evidence": provisional.get("provisional_horizon_sources") or [], "opposing_evidence": [], "limitations": ["original_horizon_unknown_preserved"],
            "required_bar_contract": legacy_swing_horizon_daily_contract_v1(horizon), "next_review_at": _iso(now), "as_of": _iso(now)}


def build_position_shadow_twin_v1(position: Mapping[str, Any], baseline: Mapping[str, Any], horizon: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Create read-only forward scenarios from the observed activation state."""
    row = dict(position or {})
    position_id = _text(row.get("asset_id") or row.get("position_id") or row.get("symbol"))
    price = _num(row.get("current_price") or row.get("market_price"))
    active = bool(position_id and price is not None and baseline.get("legacy_activation_timestamp"))
    scenarios = [
        "SHADOW_CONTINUE_HOLD", "SHADOW_EXIT_NOW", "SHADOW_EXIT_AT_PREDICTED_PEAK", "SHADOW_PROTECT_PARTIAL",
        "SHADOW_REDUCE_RISK", "SHADOW_CONTROLLED_LOSS", "SHADOW_HORIZON_SHORTEN", "SHADOW_HORIZON_EXTEND",
        "SHADOW_REPLACE_WITH_BEST_QUALIFIED", "SHADOW_NO_VALID_REPLACEMENT",
    ]
    return {
        "shadow_twin_id": f"legacy-shadow:{position_id}", "state": "POSITION_SHADOW_TWIN_ACTIVE" if active else "POSITION_SHADOW_TWIN_PENDING_EVIDENCE",
        "position_id": position_id, "symbol": _text(row.get("symbol")).upper(), "lane": _text(row.get("lane_id") or "SWING").upper(),
        "provisional_horizon": horizon.get("provisional_horizon"), "activation_price": baseline.get("activation_price"),
        "activation_timestamp": baseline.get("legacy_activation_timestamp"), "generated_at": _iso(now),
        "current_quantity": _num(row.get("qty") or row.get("quantity")), "evidence_class": "SHADOW_FORWARD_ONLY",
        "scenarios": [{"scenario": name, "state": "OUTCOME_PENDING", "broker_mutation": False} for name in scenarios],
        "limitations": ["forward_observation_required_for_counterfactual_outcomes"],
    }


def build_legacy_swing_required_evidence_v1(position: Mapping[str, Any], baseline: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Build bounded, honest evidence records from worker-owned direct inputs.

    This adapter never fetches a provider.  Missing lookback, thesis, bid/ask,
    or tradability is recorded as unavailable instead of inferred as neutral.
    """
    row = dict(position or {})
    symbol = _text(row.get("symbol")).upper()
    position_id = _text(row.get("asset_id") or row.get("position_id") or symbol)
    as_of = _iso(now)
    price = _num(row.get("current_price") or row.get("market_price"))
    activation = _num(baseline.get("activation_price"))
    bid, ask = _num(row.get("bid")), _num(row.get("ask"))
    volume = _num(row.get("volume") or row.get("recent_volume"))
    direct_thesis = _text(row.get("thesis_state") or row.get("thesis_health")).upper()
    fmp_context = dict(row.get("fmp_thesis_context") or {})
    bar_context = dict(row.get("broker_bar_record") or {})
    quote_context = dict(row.get("broker_quote_record") or {})
    asset_context = dict(row.get("broker_asset_record") or {})
    def record(kind: str, status: str, state: str, confidence: float, limitations: list[str], **extra: Any) -> dict[str, Any]:
        return {"evidence_type": kind, "record_id": f"legacy-evidence:{kind.lower()}:{position_id}", "symbol": symbol,
                "position_id": position_id, "activation_id": baseline.get("baseline_id"), "as_of": as_of,
                "last_attempt_at": as_of, "last_success_at": as_of if status == "CURRENT" else None,
                "next_refresh_at": as_of, "source": "PaperAutopilot.broker_position_snapshot", "status": status,
                "freshness": status, "quality": status, "confidence": confidence, "limitations": limitations,
                "consumer_acknowledged": True, "classification_influence": "NEUTRAL" if status == "CURRENT" else "UNAVAILABLE", **extra}
    bars = list(bar_context.get("bars") or [])
    closes = [_num(item.get("close")) for item in bars if isinstance(item, Mapping)]
    closes = [value for value in closes if value is not None and value > 0]
    volumes = [_num(item.get("volume")) for item in bars if isinstance(item, Mapping)]
    volumes = [value for value in volumes if value is not None and value >= 0]
    bar_state = _text(bar_context.get("response_state")).upper()
    bar_freshness = _text(bar_context.get("freshness_state")).upper()
    bar_quality = _text(bar_context.get("quality_state")).upper()
    bar_provider = _text(bar_context.get("canonical_provider") or bar_context.get("provider") or "AlpacaPaperBroker.historical_bars")
    bar_timeframe = _text(bar_context.get("timeframe") or "1Hour")
    required_bar_count = int(bar_context.get("required_completed_bars") or 5)
    if bar_state == "SUCCESS" and bar_freshness == "CURRENT" and bar_quality not in {"CURRENT_INSUFFICIENT", "STALE_INSUFFICIENT", "EMPTY", "INVALID", "PROVIDER_FAILED", "CONFLICT_BLOCKED"} and len(closes) >= required_bar_count:
        short = (closes[-1] / closes[-3] - 1.0) * 100.0
        medium = (closes[-1] / closes[0] - 1.0) * 100.0
        direction = "POSITIVE" if short > 0.25 and medium >= 0 else "NEGATIVE" if short < -0.25 and medium <= 0 else "STABLE"
        breakdown = "BREAKDOWN" if short < -1.0 and medium < -1.0 else "BREAKOUT" if short > 1.0 and medium > 1.0 else "NONE"
        volume_confirmation = "CONFIRMED" if len(volumes) >= 3 and volumes[-1] >= sum(volumes[-3:]) / 3.0 else "UNAVAILABLE" if not volumes else "NOT_CONFIRMED"
        momentum = record("MOMENTUM", "CURRENT", direction, 0.60 if bar_timeframe == "1Day" else 0.65, ([] if volume_confirmation != "UNAVAILABLE" else ["volume_confirmation_unavailable"]) + (["daily_swing_fallback_no_intraday_precision"] if bar_timeframe == "1Day" else []),
                          source=bar_provider, provider_record_ids=[bar_context.get("record_id")], source_provider=bar_provider,
                          fallback_used=bool(bar_context.get("fallback_used")), provider_comparison_state=bar_context.get("provider_comparison_state"),
                          momentum_timeframe=bar_timeframe, momentum_contract=bar_context.get("momentum_contract") or ("LEGACY_SWING_DAILY" if bar_timeframe == "1Day" else "LEGACY_SWING_HOURLY"),
                          short_term_direction=direction, medium_term_direction="POSITIVE" if medium > 0 else "NEGATIVE" if medium < 0 else "STABLE",
                          momentum_score=round((short + medium) / 2.0, 6), momentum_acceleration=round(short - medium, 6),
                          trend_strength=abs(round(medium, 6)), volume_confirmation=volume_confirmation,
                          breakout_or_breakdown_state=breakdown, recovery_state="RECOVERING" if short > 0 and medium < 0 else "NONE",
                          deterioration_state="DETERIORATING" if direction == "NEGATIVE" and breakdown != "BREAKDOWN" else "NONE", supporting_inputs=["canonical_recent_bars"])
    elif bar_freshness == "STALE":
        momentum = record("MOMENTUM", "STALE", "STALE", 0.0, ["stale_canonical_bar_record"], source=bar_provider, source_provider=bar_provider, short_term_direction="STALE", supporting_inputs=[])
    elif bar_quality == "CONFLICT_BLOCKED":
        momentum = record("MOMENTUM", "UNAVAILABLE", "CONFLICTING", 0.0, ["material_provider_bar_conflict"], source=bar_provider, source_provider=bar_provider, short_term_direction="UNAVAILABLE", supporting_inputs=[])
    elif bar_state == "SUCCESS":
        momentum = record("MOMENTUM", "UNAVAILABLE", "INSUFFICIENT", 0.0, ["insufficient_canonical_bar_count"], source=bar_provider, source_provider=bar_provider, short_term_direction="UNAVAILABLE", supporting_inputs=[])
    elif not bar_context and price is not None and activation is not None and row.get("recent_price_path"):
        change = (price / activation - 1.0) * 100.0 if activation else 0.0
        momentum_state = "POSITIVE" if change > 0 else "NEGATIVE" if change < 0 else "STABLE"
        momentum = record("MOMENTUM", "CURRENT", momentum_state, 0.55, [], short_term_direction=momentum_state, momentum_score=change, supporting_inputs=["activation_price", "current_price", "recent_price_path"])
    else:
        momentum = record("MOMENTUM", "UNAVAILABLE", "UNAVAILABLE", 0.0, ["recent_price_path_required"], short_term_direction="UNAVAILABLE", supporting_inputs=[])
    if direct_thesis in {"INTACT", "WEAKENING", "MATERIALLY_DETERIORATED", "BROKEN", "CONFLICTING"}:
        thesis = record("THESIS_STATE", "CURRENT", direct_thesis, 0.60, [], thesis_state=direct_thesis, direct_evidence=True)
    elif str(fmp_context.get("response_state") or "").upper() == "SUCCESS" and dict(fmp_context.get("normalized_fields") or {}):
        # Profile context proves current provider support but cannot invent an
        # original thesis or independently assert an invalidation.
        thesis = record(
            "THESIS_STATE", "CURRENT", "UNKNOWN", 0.45,
            ["original_thesis_unavailable_forward_monitoring_baseline"],
            thesis_state="UNKNOWN", direct_evidence=False,
            source="FMP.company_profile", fmp_record_id=fmp_context.get("record_id"),
            endpoint_family=fmp_context.get("endpoint_family"),
            supporting_inputs=sorted(dict(fmp_context.get("normalized_fields") or {}).keys()),
        )
    elif str(fmp_context.get("freshness_state") or "").upper() == "STALE" and dict(fmp_context.get("normalized_fields") or {}):
        thesis = record(
            "THESIS_STATE", "STALE", "UNKNOWN", 0.0,
            ["stale_fmp_profile_context"], thesis_state="UNKNOWN", direct_evidence=False,
            source="FMP.company_profile", fmp_record_id=fmp_context.get("record_id"),
            endpoint_family=fmp_context.get("endpoint_family"),
        )
    else:
        limitation = str(fmp_context.get("error_category") or "original_or_current_thesis_evidence_unavailable")
        thesis = record("THESIS_STATE", "UNAVAILABLE", "UNKNOWN", 0.0, [limitation], thesis_state="UNKNOWN", direct_evidence=False,
                        source="FMP.company_profile" if fmp_context else "PaperAutopilot.broker_position_snapshot",
                        fmp_record_id=fmp_context.get("record_id"), endpoint_family=fmp_context.get("endpoint_family"))
    quote_bid, quote_ask = _num(quote_context.get("bid")), _num(quote_context.get("ask"))
    quote_current = _text(quote_context.get("freshness_state")).upper() == "CURRENT" and _text(quote_context.get("response_state")).upper() == "SUCCESS"
    asset_current = _text(asset_context.get("freshness_state")).upper() == "CURRENT" and _text(asset_context.get("response_state")).upper() == "SUCCESS"
    # Retain the established worker-owned direct broker snapshot contract when
    # a caller has not supplied any canonical market record yet.  Once a
    # canonical record exists, its freshness and validation are authoritative.
    direct_snapshot_available = not quote_context and not asset_context and bid is not None and ask is not None and row.get("tradable") is not None
    if quote_current:
        bid, ask = quote_bid, quote_ask
    tradable = asset_context.get("tradable") if asset_current else row.get("tradable")
    liquidity_current = (quote_current and asset_current) or direct_snapshot_available
    if bid is not None and ask is not None and bid > 0 and ask >= bid and bool(tradable) and liquidity_current:
        spread_pct = (ask - bid) / max((ask + bid) / 2.0, 1e-9) * 100.0
        state = "ACCEPTABLE" if spread_pct <= 1.0 else "THIN" if spread_pct <= 2.0 else "POOR"
        source = "AlpacaPaperBroker.latest_quote+asset_metadata" if quote_current else "PaperAutopilot.broker_position_snapshot"
        liquidity = record("LIQUIDITY", "CURRENT", state, 0.65, [] if volume is not None else ["volume_unavailable"], source=source, quote_record_id=quote_context.get("record_id"), asset_record_id=asset_context.get("record_id"), bid=bid, ask=ask, spread_percentage=spread_pct, recent_volume=volume, tradable=True, liquidity_state=state)
    elif _text(quote_context.get("freshness_state")).upper() == "STALE" or _text(asset_context.get("freshness_state")).upper() == "STALE":
        liquidity = record("LIQUIDITY", "STALE", "STALE", 0.0, ["stale_canonical_quote_or_asset_record"], source="AlpacaPaperBroker.latest_quote+asset_metadata", liquidity_state="STALE", tradable=asset_context.get("tradable"))
    elif asset_current and asset_context.get("tradable") is False:
        liquidity = record("LIQUIDITY", "CURRENT", "NOT_TRADABLE", 0.7, ["broker_asset_not_tradable"], source="AlpacaPaperBroker.asset_metadata", liquidity_state="NOT_TRADABLE", tradable=False)
    else:
        liquidity = record("LIQUIDITY", "UNAVAILABLE", "UNAVAILABLE", 0.0, ["bid_ask_and_tradability_required"], liquidity_state="UNAVAILABLE", tradable=row.get("tradable"))
    return {"MOMENTUM": momentum, "THESIS_STATE": thesis, "LIQUIDITY": liquidity}


def legacy_swing_canary_policy_v1(decision: Mapping[str, Any], *, governance_pass: bool = True) -> dict[str, Any]:
    """Fail closed until a separately configured PaperAutopilot legacy policy exists."""
    row = dict(decision or {})
    actionable = row.get("classification") in {"THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "PROTECT_PROFIT", "PROTECT_PARTIAL", "REDUCE_RISK", "REPLACE_CANDIDATE", "DUST_CLEANUP_REVIEW"}
    evidence_ok = bool(row.get("current_direct_confirmation")) and bool(row.get("forward_baseline", {}).get("legacy_activation_timestamp"))
    state = "LEGACY_CANARY_ELIGIBLE" if actionable and evidence_ok and governance_pass and bool(row.get("legacy_canary_execution_enabled")) else "LEGACY_CANARY_ADVISORY_ONLY" if not actionable else "LEGACY_CANARY_POLICY_BLOCKED"
    return {
        "policy_id": "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1", "state": state,
        "max_exit_submissions_per_cycle": 1, "max_active_exit_orders": 1,
        "execution_enabled": bool(row.get("legacy_canary_execution_enabled")), "paper_action_ready": False,
        "blocker": "LEGACY_CANARY_RUNTIME_SWITCH_DISABLED" if not bool(row.get("legacy_canary_execution_enabled")) else "CURRENT_DIRECT_CONFIRMATION_REQUIRED" if not evidence_ok else None,
        "owner": "PaperAutopilot.authorized_lane_exit_pending", "governance_pass": bool(governance_pass),
    }


def classify_position_cohort_v1(position: Mapping[str, Any]) -> dict[str, Any]:
    row = dict(position or {})
    quantity = abs(_num(row.get("qty") or row.get("quantity")) or 0.0)
    value = abs(_num(row.get("market_value")) or 0.0)
    contract = _text(row.get("contract_id") or row.get("pretrade_decision_contract_id"))
    candidate = _text(row.get("candidate_id") or row.get("source_candidate_id"))
    broker_id = _text(row.get("asset_id") or row.get("position_id") or row.get("symbol"))
    if quantity <= 0 or value < 0.01:
        cohort = "DUST_POSITION"
    elif not broker_id:
        cohort = "BROKER_RESIDUE_POSITION"
    elif contract and candidate:
        cohort = "NEW_COMPLETE_CONTRACT_POSITION"
    elif candidate or _text(row.get("lifecycle_id")):
        cohort = "LEGACY_PARTIAL_LINEAGE_POSITION"
    else:
        cohort = "LEGACY_PRE_CONTRACT_POSITION"
    return {"cohort": cohort, "position_id": broker_id, "legacy_forward_only_management": cohort.startswith("LEGACY"),
            "original_history_state": "UNAVAILABLE" if cohort.startswith("LEGACY") else "AVAILABLE"}


def _parse_iso(value: Any) -> datetime | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def build_position_management_overlay_v1(
    position: Mapping[str, Any],
    *,
    lifecycle_decision: Mapping[str, Any] | None = None,
    prior_review: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Attach one conservative lifecycle-management view to a broker position.

    This is an overlay owned by the existing unified lifecycle decision owner,
    not a second position store or exit engine.  Legacy slot exclusion is
    deliberately impossible without a durable, explicit approval reference.
    """
    row = dict(position or {})
    decision = dict(lifecycle_decision or {})
    prior = dict(prior_review or {})
    current = now or datetime.now(timezone.utc)
    cohort = classify_position_cohort_v1(row)
    symbol = _text(row.get("symbol")).upper()
    position_id = _text(row.get("asset_id") or row.get("position_id") or symbol)
    lane = _text(row.get("lane_id") or decision.get("lane") or "SWING").upper()
    original_lane = _text(row.get("original_lane") or row.get("lane_id") or decision.get("lane") or "UNKNOWN").upper()
    original_strategy = _text(row.get("original_strategy") or row.get("strategy") or row.get("strategy_archetype") or "UNKNOWN")
    original_horizon = _text(row.get("original_horizon") or row.get("intended_horizon") or decision.get("original_horizon") or "UNKNOWN")
    lifecycle_id = _text(row.get("lifecycle_id"))
    candidate_id = _text(row.get("candidate_id") or row.get("source_candidate_id"))
    contract_id = _text(row.get("contract_id") or row.get("pretrade_decision_contract_id"))
    reconstruction_id = _text(row.get("reconstruction_id") or row.get("historical_reconstruction_id"))
    age = _num(row.get("position_age_days") or row.get("days_held") or row.get("age_days"))
    if age is None:
        entry_time = _parse_iso(row.get("entry_timestamp") or row.get("opened_at"))
        age = max(0.0, (current - entry_time).total_seconds() / 86400.0) if entry_time else None
    prior_next_review = _parse_iso(prior.get("next_review_at") or row.get("next_review_at"))
    prior_last_review = _parse_iso(prior.get("last_review_at") or row.get("last_review_at"))
    duplicate = bool(row.get("duplicate_exposure") or _text(row.get("duplicate_exposure_state")).upper() in {"DUPLICATE", "DUPLICATE_EXPOSURE"})
    day_drift = original_lane == "DAY" and (age is not None and age > 1.25) and not bool(row.get("hold_exception_approved"))
    stale_active = prior_next_review is not None and prior_next_review < current
    reconstructable = bool(reconstruction_id or row.get("reconstruction_state") in {"RECONSTRUCTION_COMPLETE", "RECONSTRUCTION_PARTIAL"})
    linked = bool(lifecycle_id or candidate_id)
    legacy = bool(cohort.get("legacy_forward_only_management"))
    if duplicate:
        classification, reason = "DUPLICATE_OR_CONFLICTED_POSITION", "DUPLICATE_EXPOSURE_REQUIRES_RECONCILIATION"
    elif day_drift:
        classification, reason = "DAY_HORIZON_DRIFT_POSITION", "DAY_POSITION_EXCEEDED_SAME_SESSION_HORIZON"
    elif stale_active and not legacy:
        classification, reason = "STALE_ACTIVE_POSITION", "NEXT_REVIEW_OVERDUE"
    elif not legacy:
        classification, reason = "CURRENT_MANAGED_POSITION", "COMPLETE_CURRENT_LIFECYCLE_CONTRACT"
    elif reconstructable:
        classification, reason = "LEGACY_RECONSTRUCTABLE_POSITION", "RECONSTRUCTED_LINEAGE_AVAILABLE_NOT_BROKER_TRUTH"
    elif linked:
        classification, reason = "LEGACY_LINKED_POSITION", "PARTIAL_LEGACY_LINEAGE_AVAILABLE"
    elif symbol:
        classification, reason = "LEGACY_UNLINKED_POSITION", "BROKER_POSITION_WITHOUT_CURRENT_LIFECYCLE_LINEAGE"
    else:
        classification, reason = "BROKER_ONLY_POSITION", "BROKER_POSITION_IDENTIFIER_INCOMPLETE"
    management_cohort = "LEGACY_POSITION_RESOLUTION" if classification.startswith("LEGACY_") else _text(row.get("management_cohort") or "CURRENT_MANAGED")
    approval_id = _text(row.get("legacy_resolution_approval_id") or prior.get("legacy_resolution_approval_id"))
    approved = bool(row.get("legacy_resolution_approved") or prior.get("legacy_resolution_approved")) and bool(approval_id)
    slot_exclusion = bool(
        management_cohort == "LEGACY_POSITION_RESOLUTION"
        and approved
        and bool(row.get("legacy_slot_exclusion_approved") or prior.get("legacy_slot_exclusion_approved"))
    )
    current_thesis = _text(decision.get("classification") or row.get("thesis_state") or prior.get("current_thesis") or "THESIS_REVALIDATION_REQUIRED").upper()
    exit_readiness = _text(decision.get("classification") or row.get("exit_readiness_state") or prior.get("exit_readiness_state") or "INSUFFICIENT_EVIDENCE").upper()
    review_hours = 1 if classification in {"STALE_ACTIVE_POSITION", "DAY_HORIZON_DRIFT_POSITION", "DUPLICATE_OR_CONFLICTED_POSITION"} else 4 if management_cohort == "LEGACY_POSITION_RESOLUTION" else 24
    next_review = current + timedelta(hours=review_hours)
    if prior_next_review and prior_next_review >= current:
        next_review = prior_next_review
    return {
        "schema_version": "astra_position_management_overlay_v1",
        "position_id": position_id,
        "symbol": symbol,
        "classification": classification,
        "classification_reason": reason,
        "classification_confidence": 0.9 if classification == "CURRENT_MANAGED_POSITION" else 0.7 if linked or reconstructable else 0.5,
        "lifecycle_owner": "engine.astra_unified_position_lifecycle_v1.build_unified_position_lifecycle_decision_v1",
        "exit_owner": "PaperAutopilot.authorized_lane_exit_pending",
        "capacity_owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
        "truth_owner": "PaperAutopilot._record_legacy_swing_exit_broker_update",
        "original_lane": original_lane,
        "original_strategy": original_strategy,
        "original_horizon": original_horizon,
        "management_cohort": management_cohort,
        "decreasing_only": management_cohort == "LEGACY_POSITION_RESOLUTION",
        "no_new_legacy_entries": True,
        "legacy_resolution_approval_required": management_cohort == "LEGACY_POSITION_RESOLUTION",
        "legacy_resolution_approved": approved,
        "legacy_resolution_approval_id": approval_id or None,
        "active_slot_exclusion_eligible": management_cohort == "LEGACY_POSITION_RESOLUTION",
        "active_slot_exclusion_approved": slot_exclusion,
        "full_risk_included": True,
        "current_thesis": current_thesis,
        "exit_readiness_state": exit_readiness,
        "position_age_days": round(age, 4) if age is not None else None,
        "last_review_at": _iso(prior_last_review or current),
        "next_review_at": _iso(next_review),
        "review_state": "OVERDUE_REVIEW" if stale_active else "SCHEDULED_REVIEW",
        "hold_exception_state": "HOLD_EXCEPTION_APPROVED" if bool(row.get("hold_exception_approved")) else "THESIS_REVALIDATION_REQUIRED" if classification in {"DAY_HORIZON_DRIFT_POSITION", "STALE_ACTIVE_POSITION"} else "NOT_REQUIRED",
        "authoritative_broker_truth": False,
        "reconstruction_is_context_only": reconstructable,
        "automatic_exit_authorized": False,
        "automatic_capacity_release_authorized": False,
        "as_of": _iso(current),
    }


def build_position_resolution_inventory_v1(
    positions: Sequence[Mapping[str, Any]],
    *,
    prior_reviews_by_position: Mapping[str, Mapping[str, Any]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a read-only inventory using the existing lifecycle owner only."""
    previous = {str(key): dict(value or {}) for key, value in dict(prior_reviews_by_position or {}).items()}
    rows = []
    for raw in positions:
        if not isinstance(raw, Mapping):
            continue
        position = dict(raw)
        key = _text(position.get("asset_id") or position.get("position_id") or position.get("symbol"))
        rows.append(build_position_management_overlay_v1(position, prior_review=previous.get(key), now=now))
    counts: dict[str, int] = {}
    for row in rows:
        state = _text(row.get("classification")) or "UNKNOWN"
        counts[state] = counts.get(state, 0) + 1
    legacy_rows = [row for row in rows if row.get("management_cohort") == "LEGACY_POSITION_RESOLUTION"]
    approved = [row for row in legacy_rows if row.get("active_slot_exclusion_approved")]
    missing_owner = [row.get("symbol") for row in rows if not row.get("lifecycle_owner")]
    missing_thesis = [row.get("symbol") for row in rows if not row.get("current_thesis")]
    missing_review = [row.get("symbol") for row in rows if not row.get("next_review_at")]
    return {
        "schema_version": "astra_position_resolution_inventory_v1",
        "owner": "engine.astra_unified_position_lifecycle_v1",
        "position_projection_owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
        "positions_processed": len(rows),
        "classification_counts": counts,
        "legacy_positions_proposed": len(legacy_rows),
        "legacy_positions_approved": len(approved),
        "active_slot_exclusion_count": len(approved),
        "full_risk_inclusion_count": sum(1 for row in rows if row.get("full_risk_included")),
        "missing_lifecycle_owner": missing_owner,
        "missing_current_thesis": missing_thesis,
        "missing_next_review": missing_review,
        "no_new_legacy_entries": True,
        "automatic_migration_enabled": False,
        "automatic_exit_authorized": False,
        "review_rows": rows,
    }


def _evidence_row(
    name: str,
    *,
    available: bool,
    matched: bool = False,
    evidence_class: str = "UNAVAILABLE",
    owner: str,
    weight: float = 0.0,
    influence: str = "NONE",
    limitation: str | None = None,
) -> dict[str, Any]:
    """Create an honest source-consumption row for the lifecycle ledger."""
    retrieved = bool(available)
    weighted = bool(matched and weight > 0.0)
    consumed = bool(weighted)
    return {
        "source": name,
        "owner": owner,
        "evidence_class": evidence_class if available else "UNAVAILABLE",
        "available": bool(available),
        "retrieved": retrieved,
        "matched": bool(matched),
        "weighted": weighted,
        "consumed": consumed,
        "influenced_decision": bool(consumed and influence != "NONE"),
        "influence_weight": round(max(0.0, min(1.0, weight)), 4),
        "influence_direction": influence,
        "freshness": "CURRENT_OR_CACHED_BOUNDED" if available else "UNAVAILABLE",
        "limitation": limitation,
        "consumer_acknowledgements": {
            "RETRIEVED_FOR_POSITION": retrieved,
            "MATCHED_TO_POSITION": bool(matched),
            "WEIGHTED_FOR_LIFECYCLE": weighted,
            "CONSUMED_BY_UNIFIED_DECISION": consumed,
            "INFLUENCED_CLASSIFICATION": bool(consumed and influence != "NONE"),
            "PERSISTED_FOR_OUTCOME_CALIBRATION": consumed,
        },
    }


def retrieve_position_lifecycle_evidence_v1(
    position: Mapping[str, Any],
    *,
    lifecycle_plan: Mapping[str, Any] | None = None,
    evidence_context: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_records_per_source: int = 25,
) -> dict[str, Any]:
    """Consume the existing bounded position-intelligence context once.

    This owner does not scan stores or fetch market data.  Its caller supplies
    the canonical, bounded context assembled by ``_position_intelligence_context_v1``.
    That keeps GET diagnostics read-only and makes unavailable per-position
    evidence explicit rather than silently treating aggregate evidence as a match.
    """
    del now, max_records_per_source  # The upstream context owns bounded reads and freshness.
    row, plan, context = dict(position or {}), dict(lifecycle_plan or {}), dict(evidence_context or {})
    direct = bool(row.get("current_price") or row.get("market_price") or row.get("unrealized_plpc") is not None)
    profile = dict(context.get("symbol_profile") or context.get("symbol_behavior") or {})
    lifecycle = bool(context.get("historical_similarity") or context.get("excursion"))
    replay = bool(context.get("replay_evidence"))
    replacement = dict(context.get("replacement_analysis") or {})
    opportunity = bool(context.get("opportunity_cost_state"))
    lineage = dict(context.get("lineage") or {})
    has_plan = bool(plan or lineage.get("recommendation_id") or context.get("expected_hold_duration_days"))
    rows = [
        _evidence_row("current_direct", available=direct, matched=direct, evidence_class="CURRENT_DIRECT", owner="alpaca_paper_status_v1.positions", weight=1.0 if direct else 0.0, influence="PRIMARY_CLASSIFICATION", limitation=None if direct else "current_quote_or_position_return_missing"),
        _evidence_row("lifecycle_plan", available=has_plan, matched=has_plan, evidence_class="CURRENT_CONTRACT" if has_plan else "UNAVAILABLE", owner="broker_truth_records_v1/position_lineage", weight=0.9 if has_plan else 0.0, influence="HORIZON_AND_CONTEXT", limitation="legacy_position_without_original_contract" if not has_plan else None),
        _evidence_row("symbol_behavior", available=bool(profile), matched=bool(profile), evidence_class="CURRENT_SYMBOL_DIRECT" if profile else "UNAVAILABLE", owner="symbol_behavior_profiles_v1", weight=0.45 if profile else 0.0, influence="CONFIDENCE_CONTEXT", limitation="symbol_profile_unavailable" if not profile else None),
        _evidence_row("historical_lifecycle", available=lifecycle, matched=lifecycle, evidence_class="HISTORICAL_SYMBOL_SUPPORTED" if lifecycle else "UNAVAILABLE", owner="trade_lifecycle_excursion_v2.summary_index", weight=0.35 if lifecycle else 0.0, influence="CONTEXTUAL_CALIBRATION", limitation="no_bounded_symbol_lifecycle_match" if not lifecycle else None),
        _evidence_row("replay", available=replay, matched=replay, evidence_class="REPLAY_SUPPORTED" if replay else "UNAVAILABLE", owner="replay_counterfactual_learning_v2.summary_index", weight=0.25 if replay else 0.0, influence="CONTEXTUAL_CALIBRATION", limitation="no_bounded_symbol_replay_match" if not replay else None),
        _evidence_row("shadow", available=bool(context.get("shadow_evidence")), matched=bool(context.get("shadow_evidence")), evidence_class="SHADOW_SUPPORTED", owner="realistic_shadow_evidence_learning_lab_v1", weight=0.20 if context.get("shadow_evidence") else 0.0, influence="CONTEXTUAL_CALIBRATION", limitation="no_position_specific_shadow_match" if not context.get("shadow_evidence") else None),
        _evidence_row("taught_lessons", available=bool(context.get("taught_lessons")), matched=bool(context.get("taught_lessons")), evidence_class="TAUGHT_SUPPORTED", owner="canonical_lifecycle_lessons_v1", weight=0.20 if context.get("taught_lessons") else 0.0, influence="CONTEXTUAL_CALIBRATION", limitation="no_position_specific_taught_lesson_match" if not context.get("taught_lessons") else None),
        _evidence_row("opportunity_cost", available=opportunity, matched=opportunity, evidence_class="AGGREGATE_ADVISORY", owner="opportunity_cost_learning_v1.summary_index", weight=0.30 if opportunity else 0.0, influence="REPLACEMENT_CONTEXT", limitation="opportunity_cost_not_available" if not opportunity else None),
        _evidence_row("replacement", available=bool(replacement), matched=bool(replacement.get("candidate")), evidence_class="CURRENT_CANDIDATE_DIRECT" if replacement.get("candidate") else "AGGREGATE_ADVISORY", owner="paper_opportunity_allocation_engine_v1", weight=0.40 if replacement.get("candidate") else 0.0, influence="REPLACEMENT_CONTEXT", limitation=str(replacement.get("reason") or "no_eligible_replacement") if not replacement.get("candidate") else None),
    ]
    return {
        "position_id": _text(row.get("asset_id") or row.get("position_id") or row.get("symbol")),
        "symbol": _text(row.get("symbol")).upper(),
        "evidence_rows": rows,
        "retrieved_count": sum(1 for item in rows if item["retrieved"]),
        "matched_count": sum(1 for item in rows if item["matched"]),
        "weighted_count": sum(1 for item in rows if item["weighted"]),
        "consumed_count": sum(1 for item in rows if item["consumed"]),
        "influenced_count": sum(1 for item in rows if item["influenced_decision"]),
        "unavailable_sources": [item["source"] for item in rows if not item["available"]],
        "context": context,
    }


def classify_legacy_swing_lifecycle_v1(
    position: Mapping[str, Any], *, evidence: Mapping[str, Any], confidence: float,
) -> dict[str, Any]:
    """Classify legacy SWING positions from explicit current evidence.

    A positive hold is deliberately hard to earn: absent, stale, conflicting,
    or low-confidence evidence is never coerced into ``HOLD_AS_PLANNED``.
    """
    row = dict(position or {})
    evidence_rows = list(evidence.get("evidence_rows") or [])
    direct_row = next((item for item in evidence_rows if item.get("source") == "current_direct"), {})
    price = _num(row.get("current_price") or row.get("market_price"))
    ret = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc"))
    if ret is not None and abs(ret) <= 1:
        ret *= 100.0
    momentum = _text(row.get("momentum_state") or row.get("momentum") or row.get("trend_state")).upper()
    thesis = _text(row.get("thesis_state") or row.get("thesis_health")).upper()
    liquidity = _text(row.get("liquidity_state") or row.get("liquidity")).upper()
    catalyst = _text(row.get("catalyst_state")).upper()
    regime = _text(row.get("regime_state") or row.get("regime")).upper()
    sector = _text(row.get("sector_state") or row.get("sector")).upper()
    giveback = _num(row.get("profit_giveback_pct") or row.get("giveback_pct"))
    return_per_day = _num(row.get("return_per_day") or row.get("return_per_day_pct"))
    opportunity = _text(row.get("opportunity_cost_state")).upper()
    replacement = bool(row.get("replacement_qualified") or row.get("replacement_candidate"))
    explicit_conflict = bool(row.get("evidence_conflicting") or row.get("conflicting_evidence"))
    stale = bool(row.get("quote_stale") or str(row.get("quote_freshness") or "").upper() == "STALE")
    missing = []
    if price is None:
        missing.append("CURRENT_QUOTE")
    if not momentum:
        missing.append("MOMENTUM")
    if not thesis:
        missing.append("THESIS_STATE")
    if not liquidity:
        missing.append("LIQUIDITY")
    components = {
        "thesis_integrity": thesis or "UNKNOWN", "momentum": momentum or "UNKNOWN", "liquidity": liquidity or "UNKNOWN",
        "quote_freshness": "STALE" if stale else "CURRENT" if price is not None else "MISSING",
        "giveback": giveback, "return_per_day": return_per_day, "opportunity_cost": opportunity or "UNKNOWN",
        "replacement_qualified": replacement, "catalyst": catalyst or "UNKNOWN", "regime": regime or "UNKNOWN",
        "sector": sector or "UNKNOWN", "evidence_complete": not missing and not stale,
        "evidence_conflicting": explicit_conflict, "direct_evidence_consumed": bool(direct_row.get("consumed")),
    }
    suppressed = []
    if _text(row.get("symbol")) == "" or not bool(direct_row.get("available")):
        state, reason = "INSUFFICIENT_EVIDENCE", "CURRENT_DIRECT_EVIDENCE_REQUIRED"
    elif explicit_conflict:
        state, reason = "CONFLICTING_EVIDENCE", "MATERIAL_EVIDENCE_CONFLICT"
    elif stale:
        state, reason = "INSUFFICIENT_EVIDENCE", "STALE_CURRENT_QUOTE"
    elif missing:
        state, reason = "INSUFFICIENT_EVIDENCE", f"MISSING_{missing[0]}"
    elif confidence < 0.50:
        state, reason = "LOW_CONFIDENCE", "CLASSIFICATION_CONFIDENCE_BELOW_MINIMUM"
    elif thesis in {"BROKEN", "INVALID", "THESIS_BROKEN"} and bool(row.get("hard_invalidation") or row.get("direct_thesis_invalidation")):
        state, reason = "THESIS_BROKEN", "DIRECT_THESIS_INVALIDATION"
    elif thesis in {"BROKEN", "DETERIORATING"} and ret is not None and ret < 0 and bool(row.get("controlled_loss_preferred")):
        state, reason = "CONTROLLED_LOSS_ACCEPTABLE", "DIRECT_LOSS_CONTINUATION_DISADVANTAGE"
    elif replacement and opportunity in {"HIGH", "ELEVATED"}:
        state, reason = "REPLACE_CANDIDATE", "QUALIFIED_REPLACEMENT_FORWARD_VALUE_ADVANTAGE"
    elif ret is not None and ret > 0 and giveback is not None and giveback >= 2.0:
        state, reason = "PROTECT_PROFIT", "MATERIAL_PROFIT_GIVEBACK"
    elif sum((liquidity in {"POOR", "DETERIORATING"}, momentum in {"COLLAPSE", "NEGATIVE"}, thesis == "DETERIORATING", bool(row.get("portfolio_risk_elevated") or row.get("concentration_risk")))) >= 2:
        state, reason = "REDUCE_RISK", "DIRECT_RISK_DETERIORATION"
    elif bool(row.get("exit_concern") or row.get("recovery_stalled")):
        state, reason = "EXIT_REVIEW", "EXIT_EVIDENCE_REQUIRES_CONFIRMATION"
    elif momentum in {"WEAK", "DETERIORATING", "COLLAPSE", "NEGATIVE"} or liquidity in {"POOR", "DETERIORATING"} or giveback not in (None, 0.0) or (return_per_day is not None and return_per_day < 0):
        state, reason = "HOLD_WITH_WATCH", "MONITORED_LIFECYCLE_RISK"
    elif thesis in {"INTACT", "HEALTHY"} and momentum in {"HEALTHY", "POSITIVE", "STABLE"} and liquidity in {"ADEQUATE", "HEALTHY", "LIQUID"}:
        state, reason = "HOLD_AS_PLANNED", "AFFIRMATIVE_CURRENT_EVIDENCE_SUPPORTS_CONTINUATION"
    else:
        state, reason = "INSUFFICIENT_EVIDENCE", "NO_AFFIRMATIVE_HOLD_EVIDENCE"
    if state != "HOLD_AS_PLANNED" and thesis in {"INTACT", "HEALTHY"}:
        suppressed.append("HOLD_AS_PLANNED")
    return {
        "classification": state, "classification_reason": reason, "classification_confidence": round(confidence, 4),
        "classification_components": components, "evidence_missing": missing,
        "evidence_stale": stale, "evidence_conflicting": explicit_conflict,
        "default_branch_used": False, "suppressed_classifications": suppressed,
    }


def build_unified_position_lifecycle_decision_v1(
    position: Mapping[str, Any], *, current_market_evidence: Mapping[str, Any] | None = None,
    lifecycle_plan: Mapping[str, Any] | None = None, learned_evidence: Mapping[str, Any] | None = None,
    shadow_evidence: Mapping[str, Any] | None = None, replacement_candidates: Sequence[Mapping[str, Any]] | None = None,
    now: datetime | None = None, evidence_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one evidence-labelled, advisory lifecycle decision per position."""
    row, market, plan, learned, shadow = dict(position or {}), dict(current_market_evidence or {}), dict(lifecycle_plan or {}), dict(learned_evidence or {}), dict(shadow_evidence or {})
    context = {**learned, **dict(evidence_context or {})}
    if shadow:
        context["shadow_evidence"] = shadow
    cohort = classify_position_cohort_v1(row)
    baseline = build_legacy_forward_baseline_v1(row, now=now)
    provisional_horizon = estimate_legacy_provisional_horizon_v1(row, baseline, now=now)
    shadow_twin = build_position_shadow_twin_v1(row, baseline, provisional_horizon, now=now)
    if shadow_twin.get("state") == "POSITION_SHADOW_TWIN_ACTIVE":
        context["shadow_evidence"] = shadow_twin
    context["forward_baseline"] = baseline
    context["provisional_horizon"] = provisional_horizon
    evidence = retrieve_position_lifecycle_evidence_v1(row, lifecycle_plan=plan, evidence_context=context, now=now)
    lane = _text(row.get("lane_id") or plan.get("lane") or "SWING").upper()
    original_horizon = _text(row.get("intended_horizon") or row.get("paper_entry_horizon_style") or plan.get("intended_horizon"))
    days = _num(row.get("days_held") or row.get("position_age_days")) or 0.0
    ret = _num(row.get("unrealized_return_pct") or row.get("unrealized_plpc"))
    if ret is not None and abs(ret) <= 1:
        ret *= 100.0
    direct = bool(market or next((item for item in evidence["evidence_rows"] if item["source"] == "current_direct" and item["available"]), None))
    horizon_state = "HORIZON_EXPIRED" if original_horizon == "day_trade" and days > 1.25 else "ORIGINAL_HORIZON_MAINTAINED" if original_horizon else "HORIZON_EVIDENCE_INSUFFICIENT"
    profile = dict(context.get("symbol_profile") or context.get("symbol_behavior") or {})
    expected_upside = profile.get("expected_upside_range") or context.get("expected_upside_range")
    expected_downside = profile.get("expected_downside_range") or context.get("expected_downside_range")
    forecast_complete = bool(direct and (expected_upside or expected_downside))
    confidence = min(0.9, round(0.25 + sum(item["influence_weight"] for item in evidence["evidence_rows"] if item["consumed"]) / 4.0, 3))
    if not direct:
        confidence = 0.0
    classifier_input = {**row, **market}
    exit_state = _text(row.get("exit_readiness_state") or "").upper()
    if exit_state == "EXIT_REVIEW":
        classifier_input["exit_concern"] = True
    elif exit_state == "THESIS_BROKEN":
        classifier_input["thesis_state"] = "BROKEN"
        classifier_input["direct_thesis_invalidation"] = True
    elif exit_state == "REPLACE_CANDIDATE":
        classifier_input["replacement_qualified"] = True
    classification_detail = (
        {"classification": "DUST_CLEANUP_REVIEW", "classification_reason": "CANONICAL_DUST_COHORT",
         "classification_confidence": confidence, "classification_components": {}, "evidence_missing": [],
         "evidence_stale": False, "evidence_conflicting": False, "default_branch_used": False, "suppressed_classifications": []}
        if cohort["cohort"] == "DUST_POSITION"
        else classify_legacy_swing_lifecycle_v1(classifier_input, evidence=evidence, confidence=confidence)
    )
    state = str(classification_detail["classification"])
    policy_eligible = state in {"PROTECT_PROFIT", "PROTECT_PARTIAL", "REDUCE_RISK", "THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "REPLACE_CANDIDATE", "DUST_CLEANUP_REVIEW"}
    blocker = "HUMAN_POLICY_DECISION_REQUIRED" if policy_eligible else str(classification_detail.get("classification_reason") or "ADVISORY_CLASSIFICATION_ONLY")
    if not direct:
        blocker = "INSUFFICIENT_CURRENT_DIRECT_EVIDENCE"
    direct_confirmation = bool(direct and state in {"PROTECT_PROFIT", "THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "REPLACE_CANDIDATE", "DUST_CLEANUP_REVIEW"})
    decision = {"position_id": cohort["position_id"], "symbol": _text(row.get("symbol")).upper(), "cohort": cohort["cohort"], "lane": lane,
            "original_horizon": original_horizon or "UNKNOWN", "current_recommended_horizon": original_horizon or "UNKNOWN", "horizon_state": horizon_state,
            "forward_baseline": baseline, "provisional_horizon": provisional_horizon, "shadow_twin": shadow_twin,
            "lifecycle_plan_state": "AVAILABLE" if plan else "LEGACY_FORWARD_ONLY", "lifecycle_stage": "POSITION_ACTIVE", "classification": state,
            "consensus_state": "LOW_CONFIDENCE" if not direct else "CONSENSUS_EXIT_REVIEW" if state in {"EXIT_REVIEW", "THESIS_BROKEN"} else "CONSENSUS_HOLD_WITH_WATCH",
            "predictive_forecast_state": "FORECAST_COMPLETE" if forecast_complete else "INSUFFICIENT_EVIDENCE",
            "predicted_time_to_peak_range": context.get("predicted_time_to_peak_range"), "expected_remaining_upside_range": expected_upside,
            "expected_downside_from_hold_range": expected_downside, "recovery_probability": context.get("recovery_probability"),
            "giveback_probability": context.get("giveback_probability"), "forecast_confidence": confidence,
            "hold_forward_value": "UNKNOWN" if ret is None else round(ret, 4), "exit_now_forward_value": ret,
            "partial_protection_forward_value": "UNKNOWN", "replacement_forward_value": context.get("replacement_analysis", {}).get("expected_advantage") if isinstance(context.get("replacement_analysis"), dict) else "UNKNOWN",
            "shadow_guidance": "SHADOW_SUPPORTS_EXIT_REVIEW" if context.get("shadow_evidence") and state == "EXIT_REVIEW" else "SHADOW_SUPPORTS_HOLD" if context.get("shadow_evidence") else "SHADOW_INSUFFICIENT",
            "evidence_rows": evidence["evidence_rows"], "evidence_retrieved_count": evidence["retrieved_count"], "evidence_matched_count": evidence["matched_count"],
            "evidence_weighted_count": evidence["weighted_count"], "evidence_consumed_count": evidence["consumed_count"], "evidence_influenced_count": evidence["influenced_count"],
            "unavailable_evidence_sources": evidence["unavailable_sources"],
            "policy_eligibility": "POLICY_BLOCKED" if policy_eligible else "ADVISORY_ONLY", "paper_action_ready": False,
            "current_direct_confirmation": direct_confirmation,
            "classification_reason": classification_detail["classification_reason"], "classification_confidence": classification_detail["classification_confidence"],
            "classification_components": classification_detail["classification_components"], "evidence_missing": classification_detail["evidence_missing"],
            "evidence_stale": classification_detail["evidence_stale"], "evidence_conflicting": classification_detail["evidence_conflicting"],
            "default_branch_used": classification_detail["default_branch_used"], "suppressed_classifications": classification_detail["suppressed_classifications"],
            "exact_blocker": blocker, "next_review": "next_session" if lane != "CRYPTO" else "continuous_crypto_review",
            "monitoring_intensity": "HEIGHTENED_MONITORING" if state in {"EXIT_REVIEW", "THESIS_BROKEN"} else "NORMAL_MONITORING",
            "consumer_acknowledgements": {"LIFECYCLE_PLAN_CONSUMED_BY_POSITION_MONITOR": bool(plan), "LIFECYCLE_PLAN_CONSUMED_BY_EXIT_REVIEW": bool(plan), "LIFECYCLE_PLAN_PERSISTED_FOR_TRUTH_CALIBRATION": bool(plan), "FORWARD_BASELINE_CONSUMED": True, "PROVISIONAL_HORIZON_CONSUMED": True, "POSITION_SHADOW_TWIN_CONSUMED": shadow_twin.get("state") == "POSITION_SHADOW_TWIN_ACTIVE", "FORECAST_INFLUENCE_PERSISTED": True},
            "advisory_only": True, "paper_actions_used": 0}
    decision["legacy_canary_policy"] = legacy_swing_canary_policy_v1(decision)
    return decision
