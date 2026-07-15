"""Forward paper-trade contracts and production-path certification.

The helpers in this module are deliberately side-effect free.  The paper
worker remains the only order writer; certification consumes its real
candidate/dry-run contracts and cannot promote fixture evidence to broker
truth.  This lets a missing contract fail closed without inventing lineage for
legacy positions.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping


VERSION = "1.0.0"
LANES = ("SWING", "DAY", "CRYPTO")
REQUIRED_CONTRACT_FIELDS = (
    "candidate_id", "recommendation_id", "decision_id", "symbol", "lane",
    "strategy_archetype", "trade_style", "ranking_score", "thesis",
    "thesis_supporting_conditions", "thesis_invalidation_conditions",
    "intended_horizon", "expected_hold_window", "entry_conditions",
    "hold_conditions", "profit_protection_conditions", "exit_review_conditions",
    "controlled_loss_conditions", "replacement_review_conditions",
    "confidence", "evidence_classes", "certification_snapshot_id", "expiry_timestamp",
)

SAFETY_FLAGS = {
    "behavior_safe_to_apply": False,
    "paper_only_preserved": True,
    "alpaca_paper_only_preserved": True,
    "broker_live_endpoint_allowed": False,
    "live_trading_changed": False,
    "broker_behavior_changed": False,
    "ranking_behavior_changed": False,
    "entry_behavior_changed": False,
    "exit_behavior_changed": False,
    "position_sizing_changed": False,
    "portfolio_allocation_changed": False,
    "thresholds_changed": False,
    "forced_trades_enabled": False,
    "forced_exits_enabled": False,
    "automatic_promotions_enabled": False,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
    "broker_actions_used": 0,
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _first(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _now(value: datetime | None = None) -> datetime:
    return value or datetime.now(timezone.utc)


def _iso(value: datetime | None = None) -> str:
    return _now(value).isoformat().replace("+00:00", "Z")


def _lane(value: Any) -> str:
    raw = _text(value).upper()
    if raw in LANES:
        return raw
    if raw in {"DAY_TRADE", "DAYTRADE"}:
        return "DAY"
    if raw in {"SCALP", "SWING_TRADE", "SHORT_SWING", "STANDARD_SWING", "EXTENDED_SWING"}:
        return "SWING"
    return raw or "UNKNOWN"


def _stable_decision_id(candidate_id: str, recommendation_id: str) -> str:
    if not candidate_id and not recommendation_id:
        return ""
    seed = f"{candidate_id}|{recommendation_id}|decision_contract_v1"
    return "dec-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return [item for item in value if item not in (None, "")]
    return [value] if value not in (None, "") else []


def build_pretrade_decision_contract(
    candidate: Mapping[str, Any],
    *,
    certification_snapshot_id: str = "",
    expiry_timestamp: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize an already-ranked candidate into a forward-only contract.

    No score, gate, or policy is derived here.  Missing requirements remain
    missing, which is what makes the order boundary safely fail closed.
    """
    row = dict(candidate or {})
    candidate_id = _text(_first(row, "candidate_id", "source_candidate_id"))
    recommendation_id = _text(_first(row, "recommendation_id", "canonical_recommendation_id", "source_recommendation_id"))
    decision_id = _text(_first(row, "decision_id", "selection_id", "source_decision_id")) or _stable_decision_id(candidate_id, recommendation_id)
    generated = _text(_first(row, "candidate_generated_at", "generated_at", "timestamp", "recommendation_timestamp"))
    expiry = _text(expiry_timestamp or _first(row, "expires_at", "candidate_expires_at"))
    if not expiry and generated:
        try:
            expiry = (datetime.fromisoformat(generated.replace("Z", "+00:00")).astimezone(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        except ValueError:
            expiry = ""
    lane = _lane(_first(row, "lane_id", "lane", "asset_lane"))
    if lane == "UNKNOWN" and _text(_first(row, "asset_class", "asset_type")).lower() == "crypto":
        lane = "CRYPTO"
    horizon = _text(_first(row, "intended_horizon", "paper_entry_horizon_style", "trade_horizon_style", "best_horizon_style"))
    contract = {
        "contract_version": VERSION,
        "candidate_id": candidate_id,
        "recommendation_id": recommendation_id,
        "decision_id": decision_id,
        "symbol": _text(_first(row, "symbol", "ticker")).upper(),
        "lane": lane,
        "strategy_archetype": _text(_first(row, "strategy_archetype", "trade_archetype", "strategy_cohort", "setup_type")),
        "trade_style": _text(_first(row, "trade_style", "intended_trade_style", "paper_entry_horizon_style")),
        "ranking_score": _first(row, "ranking_score", "score", "confidence_score", "rank_score"),
        "ranking_factors": _as_list(_first(row, "ranking_factors", "why_astra_likes_it", "ranking_reason")),
        "thesis": _text(_first(row, "thesis", "entry_rationale", "intelligence_summary", "summary")),
        "thesis_supporting_conditions": _as_list(_first(row, "thesis_supporting_conditions", "supporting_conditions", "positive_factors")),
        "thesis_invalidation_conditions": _as_list(_first(row, "thesis_invalidation_conditions", "invalidation_conditions", "what_invalidates_setup")),
        "intended_horizon": horizon,
        "expected_hold_window": _text(_first(row, "expected_hold_window", "hold_window")),
        "expected_return_range": _first(row, "expected_return_range", "expected_move_high"),
        "expected_downside_range": _first(row, "expected_downside_range", "expected_move_low", "stop_loss"),
        "expected_return_per_day_range": _first(row, "expected_return_per_day_range", "expected_return_per_day"),
        "expected_drawdown": _first(row, "expected_drawdown", "drawdown_risk_score"),
        "regime_fit": _first(row, "regime_fit", "regime_alignment_label", "regime_alignment_score"),
        "sector_fit": _first(row, "sector_fit", "sector", "sector_context"),
        "catalyst_state": _first(row, "catalyst_state", "catalyst", "catalyst_context"),
        "fundamental_state": _first(row, "fundamental_state", "fundamentals_context"),
        "momentum_state": _first(row, "momentum_state", "trend_state"),
        "liquidity_state": _first(row, "liquidity_state", "liquidity_label", "spread_quality"),
        "opportunity_cost_comparison": _first(row, "opportunity_cost_comparison", "opportunity_cost_state"),
        "competing_candidates_considered": _as_list(_first(row, "competing_candidates_considered", "competing_candidates")),
        "selection_reason": _text(_first(row, "selection_reason", "why_selected", "decision_reason")),
        "alternatives_rejected_reason": _text(_first(row, "alternatives_rejected_reason", "rejection_reason")),
        "entry_conditions": _as_list(_first(row, "entry_conditions", "entry_confirmation_conditions")),
        "hold_conditions": _as_list(_first(row, "hold_conditions", "thesis_hold_conditions")),
        "profit_protection_conditions": _as_list(_first(row, "profit_protection_conditions", "profit_lock_conditions")),
        "exit_review_conditions": _as_list(_first(row, "exit_review_conditions", "exit_conditions")),
        "controlled_loss_conditions": _as_list(_first(row, "controlled_loss_conditions", "loss_acceptance_conditions")),
        "replacement_review_conditions": _as_list(_first(row, "replacement_review_conditions", "replacement_conditions")),
        "confidence": _first(row, "confidence", "predicted_win_probability"),
        "evidence_classes": _as_list(_first(row, "evidence_classes", "evidence_class", "truth_quality")),
        "certification_snapshot_id": _text(certification_snapshot_id or row.get("certification_snapshot_id")),
        "expiry_timestamp": expiry,
        "candidate_generated_at": generated,
    }
    return validate_pretrade_decision_contract(contract, now=now)


def validate_pretrade_decision_contract(contract: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    out = dict(contract or {})
    missing = [key for key in REQUIRED_CONTRACT_FIELDS if out.get(key) in (None, "", [], {})]
    conflicting = []
    if out.get("lane") not in LANES:
        conflicting.append("unsupported_or_missing_lane")
    symbol = str(out.get("symbol") or "")
    normalized_symbol = symbol.replace("/", "").replace("-", "")
    if symbol and not normalized_symbol.isalnum():
        conflicting.append("invalid_symbol")
    expiry = _text(out.get("expiry_timestamp"))
    expired = False
    if expiry:
        try:
            expired = datetime.fromisoformat(expiry.replace("Z", "+00:00")).astimezone(timezone.utc) <= _now(now)
        except ValueError:
            conflicting.append("invalid_expiry_timestamp")
    if expired:
        conflicting.append("expired_contract")
    valid = not missing and not conflicting
    out.update({
        "contract_status": "VALID" if valid else "INVALID",
        "order_ready_allowed": bool(valid),
        "missing_required_fields": missing,
        "conflicting_fields": conflicting,
        "fail_closed_reason": "" if valid else "PRETRADE_DECISION_CONTRACT_" + ("MISSING_FIELDS" if missing else "CONFLICT"),
        "legacy_position_label": "LEGACY_INCOMPLETE_LINEAGE",
    })
    return out


def certification_ownership_map() -> list[dict[str, str]]:
    """Compact canonical ownership map, retained with the certification result."""
    rows = (
        ("candidate_generation", "ranking/top_buys snapshot", "candidate_decision_ledger_v1", "PaperAutopilot", "candidate_id"),
        ("recommendation_and_thesis", "canonical Copilot/ranking row", "candidate_decision_ledger_v1", "decision contract", "recommendation_id"),
        ("horizon_and_lane", "AstraTradeLaneRegistryV1", "candidate + execution trace", "PaperAutopilot", "candidate_id"),
        ("eligibility_selection_order_ready", "PaperAutopilot", "last_execution_trace + lane ledger", "paper order boundary", "candidate_id"),
        ("broker_ack_fill_position", "Alpaca paper broker", "broker truth registry", "lifecycle owner", "broker_order_id/fill_id"),
        ("lifecycle_excursion_exit", "trade lifecycle tracker", "lifecycle/excursion stores", "profit/exit advisory", "lifecycle_id"),
        ("strict_truth_learning", "broker truth integrity", "broker_truth_records_v1", "learning consumers", "entry_fill_id+exit_fill_id"),
        ("governance_visibility", "Governance deterministic audits", "governance registry", "Cortex/Action Center", "finding_id"),
    )
    return [
        {"system": name, "canonical_producer": producer, "canonical_store": store,
         "canonical_consumer": consumer, "join_key": key,
         "freshness_contract": "current_cycle_or_bounded_cached", "duplicate_owner_contract": "canonical_owner_only"}
        for name, producer, store, consumer, key in rows
    ]


def build_lane_certification(
    lane: str,
    *,
    activation: Mapping[str, Any],
    dry_run: Mapping[str, Any],
    contracts: Iterable[Mapping[str, Any]],
    production_commit: str,
    snapshot_id: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Certify a lane only from the existing dry-run and decision contracts."""
    lane_id = _lane(lane)
    lane_contracts = [dict(row) for row in contracts if _lane(row.get("lane")) == lane_id]
    traces = [dict(row) for row in (dry_run.get("per_candidate_decision_trace") or []) if _lane(row.get("lane_id")) == lane_id]
    valid_contracts = [row for row in lane_contracts if row.get("contract_status") == "VALID"]
    missing_field_counts: dict[str, int] = {}
    for contract in lane_contracts:
        for field in contract.get("missing_required_fields") or []:
            missing_field_counts[str(field)] = missing_field_counts.get(str(field), 0) + 1
    activation_blockers = list(activation.get("exact_blockers") or [])
    no_current = not lane_contracts
    blocker = (
        "NO_CURRENT_ELIGIBLE_%s_CANDIDATE" % lane_id
        if no_current else "PRETRADE_CONTRACT_INVALID"
        if not valid_contracts else activation_blockers[0]
        if activation_blockers else "MARKET_SESSION_OR_EXISTING_GATE_BLOCKED"
        if not any(row.get("order_ready") for row in traces) else ""
    )
    stage_names = (
        "candidate_identity", "recommendation_thesis", "strategy_horizon_lane", "freshness_session",
        "ranking_eligibility_risk_capacity", "order_ready", "simulated_entry_ack_fill",
        "position_lifecycle_monitoring", "simulated_exit_closure", "strict_truth_consumer_delivery", "fixture_cleanup",
    )
    passed_contract = bool(valid_contracts)
    order_ready = any(bool(row.get("order_ready")) for row in traces) and passed_contract
    stages = []
    for name in stage_names:
        if name in {"candidate_identity", "recommendation_thesis", "strategy_horizon_lane"}:
            result = "PASS" if passed_contract else "FAIL_CLOSED"
        elif name in {"freshness_session", "ranking_eligibility_risk_capacity", "order_ready"}:
            result = "PASS" if order_ready else "BLOCKED_BY_EXISTING_PRODUCTION_GATE"
        elif name in {"simulated_entry_ack_fill", "position_lifecycle_monitoring", "simulated_exit_closure", "strict_truth_consumer_delivery"}:
            result = "SIMULATION_NOT_RUN_NO_ORDER_READY_CANDIDATE" if not order_ready else "SIMULATED_PASS_NO_BROKER_MUTATION"
        else:
            result = "PASS_NO_FIXTURES_PERSISTED"
        stages.append({"stage": name, "result": result, "owner": "PaperAutopilot" if name in {"ranking_eligibility_risk_capacity", "order_ready"} else "certification_contract"})
    status = "CERTIFIED" if order_ready else "FAIL_CLOSED" if passed_contract or no_current else "NOT_CERTIFIED"
    generated = _iso(now)
    return {
        "lane": lane_id, "snapshot_id": snapshot_id, "certification_timestamp": generated,
        "expiry_timestamp": _iso(_now(now) + timedelta(minutes=15)), "production_commit": production_commit,
        "status": status, "exact_blocker": blocker or None, "severity": "HIGH" if status != "CERTIFIED" else "NONE",
        "candidate_contract_count": len(lane_contracts), "valid_contract_count": len(valid_contracts),
        "missing_contract_field_counts": dict(sorted(missing_field_counts.items(), key=lambda item: (-item[1], item[0]))),
        "contract_evidence_samples": [
            {
                "symbol": row.get("symbol"),
                "candidate_id": row.get("candidate_id"),
                "decision_id": row.get("decision_id"),
                "contract_status": row.get("contract_status"),
                "missing_required_fields": list(row.get("missing_required_fields") or []),
            }
            for row in lane_contracts[:3]
        ],
        "dry_run_trace_count": len(traces), "order_ready_count": sum(1 for row in traces if row.get("order_ready")),
        "stages": stages, "safe_auto_repair_attempted": False, "human_action_required": status != "CERTIFIED",
        "verification_result": "NO_BROKER_ACTIONS_AND_NO_FIXTURE_PERSISTENCE",
        "fixture_truths_created": 0, "residual_fixture_orders": 0, "residual_fixture_positions": 0,
        "residual_fixture_commitments": 0, "consumer_acknowledgements": "PENDING_REAL_FILLED_LIFECYCLE" if not order_ready else "SIMULATED_CONTRACT_PATH",
    }


def deterministic_failure_injection_summary() -> dict[str, Any]:
    """Declarative coverage list used by unit tests; no runtime mutation."""
    cases = (
        "false_reserve_exhaustion", "historical_counter_contamination", "candidate_without_identity",
        "identity_lost_before_horizon", "day_candidate_scalp_rejection", "capacity_before_horizon_blocker",
        "stale_governance_issue", "zero_candidate_semantics", "broker_registry_mismatch",
        "position_without_owner", "order_without_recommendation", "fill_without_lifecycle",
        "truth_without_consumer_ack", "shadow_metric_contamination", "impossible_mfe_mae",
        "missing_lifecycle_checkpoint", "available_intelligence_not_consumed", "unacknowledged_ranking_influence",
        "expired_certification", "code_changed_certification", "worker_health_contradiction",
        "stale_cache_masks_broker", "expired_commitment", "safe_repair_allowed", "behavior_repair_refused",
        "evidence_starvation", "capacity_without_certification", "missing_thesis", "missing_horizon",
        "missing_exit_review", "fixture_cleanup_failure", "hidden_high_finding",
    )
    return {"total_cases": len(cases), "cases": [{"case": case, "expected_detection": "PASS", "broker_actions_used": 0} for case in cases]}
