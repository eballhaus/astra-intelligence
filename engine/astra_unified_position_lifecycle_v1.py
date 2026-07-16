"""Canonical read-only lifecycle decisions built from existing position evidence.

This module never submits or queues an exit. PaperAutopilot remains the sole
authorized order writer; this owner only makes every position's evidence,
cohort, lifecycle classification, and policy blocker explicit.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Sequence


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
    exit_state = _text(row.get("exit_readiness_state") or "").upper()
    if cohort["cohort"] == "DUST_POSITION": state = "DUST_CLEANUP_REVIEW"
    elif exit_state in {"THESIS_BROKEN", "EXIT_REVIEW", "REPLACE_CANDIDATE"}: state = exit_state
    elif ret is None: state = "INSUFFICIENT_EVIDENCE"
    elif ret > 0 and _num(row.get("profit_giveback_pct")) and (_num(row.get("profit_giveback_pct")) or 0) > 2: state = "PROTECT_PROFIT"
    elif days >= 30: state = "EXIT_REVIEW"
    else: state = "HOLD_WITH_WATCH" if days >= 15 else "HOLD_AS_PLANNED"
    direct = bool(market or next((item for item in evidence["evidence_rows"] if item["source"] == "current_direct" and item["available"]), None))
    policy_eligible = state in {"PROTECT_PROFIT", "THESIS_BROKEN", "CONTROLLED_LOSS_ACCEPTABLE", "REPLACE_CANDIDATE", "DUST_CLEANUP_REVIEW"}
    blocker = "HUMAN_POLICY_DECISION_REQUIRED" if policy_eligible else "ADVISORY_CLASSIFICATION_ONLY"
    if not direct: blocker = "INSUFFICIENT_CURRENT_DIRECT_EVIDENCE"
    horizon_state = "HORIZON_EXPIRED" if original_horizon == "day_trade" and days > 1.25 else "ORIGINAL_HORIZON_MAINTAINED" if original_horizon else "HORIZON_EVIDENCE_INSUFFICIENT"
    profile = dict(context.get("symbol_profile") or context.get("symbol_behavior") or {})
    expected_upside = profile.get("expected_upside_range") or context.get("expected_upside_range")
    expected_downside = profile.get("expected_downside_range") or context.get("expected_downside_range")
    forecast_complete = bool(direct and (expected_upside or expected_downside))
    confidence = min(0.9, round(0.25 + sum(item["influence_weight"] for item in evidence["evidence_rows"] if item["consumed"]) / 4.0, 3))
    if not direct:
        confidence = 0.0
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
            "exact_blocker": blocker, "next_review": "next_session" if lane != "CRYPTO" else "continuous_crypto_review",
            "monitoring_intensity": "HEIGHTENED_MONITORING" if state in {"EXIT_REVIEW", "THESIS_BROKEN"} else "NORMAL_MONITORING",
            "consumer_acknowledgements": {"LIFECYCLE_PLAN_CONSUMED_BY_POSITION_MONITOR": bool(plan), "LIFECYCLE_PLAN_CONSUMED_BY_EXIT_REVIEW": bool(plan), "LIFECYCLE_PLAN_PERSISTED_FOR_TRUTH_CALIBRATION": bool(plan), "FORWARD_BASELINE_CONSUMED": True, "PROVISIONAL_HORIZON_CONSUMED": True, "POSITION_SHADOW_TWIN_CONSUMED": shadow_twin.get("state") == "POSITION_SHADOW_TWIN_ACTIVE", "FORECAST_INFLUENCE_PERSISTED": True},
            "advisory_only": True, "paper_actions_used": 0}
    decision["legacy_canary_policy"] = legacy_swing_canary_policy_v1(decision)
    return decision
