"""Canonical read-only lifecycle decisions built from existing position evidence.

This module never submits or queues an exit. PaperAutopilot remains the sole
authorized order writer; this owner only makes every position's evidence,
cohort, lifecycle classification, and policy blocker explicit.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
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
    if bar_state == "SUCCESS" and bar_freshness == "CURRENT" and len(closes) >= 5:
        short = (closes[-1] / closes[-3] - 1.0) * 100.0
        medium = (closes[-1] / closes[0] - 1.0) * 100.0
        direction = "POSITIVE" if short > 0.25 and medium >= 0 else "NEGATIVE" if short < -0.25 and medium <= 0 else "STABLE"
        breakdown = "BREAKDOWN" if short < -1.0 and medium < -1.0 else "BREAKOUT" if short > 1.0 and medium > 1.0 else "NONE"
        volume_confirmation = "CONFIRMED" if len(volumes) >= 3 and volumes[-1] >= sum(volumes[-3:]) / 3.0 else "UNAVAILABLE" if not volumes else "NOT_CONFIRMED"
        momentum = record("MOMENTUM", "CURRENT", direction, 0.65, [] if volume_confirmation != "UNAVAILABLE" else ["volume_confirmation_unavailable"],
                          source="AlpacaPaperBroker.historical_bars", provider_record_ids=[bar_context.get("record_id")],
                          short_term_direction=direction, medium_term_direction="POSITIVE" if medium > 0 else "NEGATIVE" if medium < 0 else "STABLE",
                          momentum_score=round((short + medium) / 2.0, 6), momentum_acceleration=round(short - medium, 6),
                          trend_strength=abs(round(medium, 6)), volume_confirmation=volume_confirmation,
                          breakout_or_breakdown_state=breakdown, recovery_state="RECOVERING" if short > 0 and medium < 0 else "NONE",
                          deterioration_state="DETERIORATING" if direction == "NEGATIVE" and breakdown != "BREAKDOWN" else "NONE", supporting_inputs=["canonical_recent_bars"])
    elif bar_freshness == "STALE":
        momentum = record("MOMENTUM", "STALE", "STALE", 0.0, ["stale_canonical_bar_record"], source="AlpacaPaperBroker.historical_bars", short_term_direction="STALE", supporting_inputs=[])
    elif bar_state == "SUCCESS":
        momentum = record("MOMENTUM", "UNAVAILABLE", "INSUFFICIENT", 0.0, ["insufficient_canonical_bar_count"], source="AlpacaPaperBroker.historical_bars", short_term_direction="UNAVAILABLE", supporting_inputs=[])
    elif price is not None and activation is not None and row.get("recent_price_path"):
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
