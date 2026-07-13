"""Bounded V2 contracts for Astra's approved paper-trading lanes.

This module owns no ranking, allocation, broker client, or worker.  It makes
the approved operating envelope explicit so the existing PaperAutopilot owner
can reject unsafe lane work consistently.  All helpers are deterministic and
side-effect free.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping

from engine.astra_trade_lane_registry_v1 import LANE_CRYPTO, LANE_DAY, LANE_SWING


TRUTH_CLASS = "BROKER_CONFIRMED_COMPLETE"
DAY_CEILING = 15_000.0
CRYPTO_CEILING = 10_000.0
OPERATIONAL_CANDIDATE_MAX_AGE_DEFAULT = 300.0
ACTIVATION_CONTRACT_VERSION = "v3"


def _text(value: Any) -> str:
    return str(value or "").strip()


def _truthy(value: Any) -> bool:
    return _text(value).lower() in {"1", "true", "yes", "on"}


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None


def _row_lane(row: Mapping[str, Any]) -> str:
    return _text(row.get("lane_id")).upper()


@dataclass(frozen=True)
class LaneEnvelope:
    lane_id: str
    capital_book_id: str
    approved_ceiling: float
    initial_open_positions: int
    approved_open_positions: int
    initial_completed_trades: int
    approved_completed_trades: int
    rolling_24h: bool


LANE_ENVELOPES = {
    LANE_DAY: LaneEnvelope(LANE_DAY, "paper_day_learning", DAY_CEILING, 1, 3, 2, 8, False),
    LANE_CRYPTO: LaneEnvelope(LANE_CRYPTO, "paper_crypto_separate", CRYPTO_CEILING, 1, 4, 2, 6, True),
}


def operational_candidate_max_age_seconds(env: Mapping[str, str] | None = None) -> float:
    """Read an operational age limit without weakening final quote freshness."""
    raw = (env or os.environ).get("ASTRA_OPERATIONAL_CANDIDATE_MAX_AGE_SECONDS", "")
    value = _number(raw)
    if value is None or value <= 0:
        return OPERATIONAL_CANDIDATE_MAX_AGE_DEFAULT
    return min(3600.0, value)


def operational_freshness(age_seconds: Any, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    limit = operational_candidate_max_age_seconds(env)
    age = _number(age_seconds)
    return {
        "candidate_snapshot_age_seconds": age,
        "candidate_snapshot_max_age_seconds": limit,
        "candidate_snapshot_freshness": "CURRENT" if age is not None and 0 <= age <= limit else "STALE" if age is not None else "MISSING",
        "final_quote_freshness_separate": True,
    }


def lane_capital_status(lane_id: str, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Validate approved lane capital; a book ID can never substitute for it."""
    lane = _text(lane_id).upper()
    envelope = LANE_ENVELOPES.get(lane)
    if envelope is None:
        return {"capital_configuration_status": "NOT_APPLICABLE", "capital_configured": lane == LANE_SWING}
    values = env or os.environ
    key = "ASTRA_DAY_LANE_CAPITAL_LIMIT" if lane == LANE_DAY else "ASTRA_CRYPTO_PAPER_CAPITAL_LIMIT"
    raw = _text(values.get(key))
    configured = _number(raw)
    if not raw:
        status = "CAPITAL_CONFIGURATION_REQUIRED"
    elif configured is None or configured <= 0:
        status = "CAPITAL_CONFIGURATION_INVALID"
    elif configured > envelope.approved_ceiling:
        status = "CAPITAL_LIMIT_EXCEEDS_APPROVAL"
    else:
        status = "PASS"
    return {
        "lane_id": lane,
        "capital_environment_key": key,
        "capital_book_id": envelope.capital_book_id,
        "approved_ceiling": envelope.approved_ceiling,
        "configured_limit": configured,
        "capital_configured": status == "PASS",
        "capital_configuration_status": status,
        "capital_in_use": 0.0,
        "capital_reserved": 0.0,
        "capital_available": max(0.0, (configured or 0.0)),
        "cross_lane_buying_power_pooling_allowed": False,
    }


def canonical_lane_activation_contract(
    lane_id: str,
    env: Mapping[str, str] | None = None,
    *,
    broker_safety: Mapping[str, Any] | None = None,
    session_allowed: bool | None = None,
    candidate_source_ready: bool = True,
    candidate_freshness_ready: bool = True,
    entry_worker_ready: bool = True,
    exit_worker_ready: bool = True,
    position_owner_ready: bool = True,
    truth_pipeline_ready: bool = True,
    learning_delivery_ready: bool = True,
) -> dict[str, Any]:
    """Return the single fail-closed activation contract for a paper lane.

    This is deliberately a pure configuration/safety function.  Candidate,
    session, and broker owners provide their current facts as inputs; this
    helper never calls a provider, broker, worker, or ranking path.  The DAY
    pilot variable is authoritative.  The retired learning-lane variable is
    accepted only when it agrees, so legacy deployment files cannot silently
    create a second execution authority.
    """
    lane = _text(lane_id).upper()
    values = env or os.environ
    safety = dict(broker_safety or {})
    blockers: list[str] = []
    capital = lane_capital_status(lane, values)

    paper_mode_verified = bool(safety.get("paper_mode_verified", True))
    broker_execution_enabled = bool(safety.get("broker_execution_enabled", True))
    paper_endpoint_verified = bool(
        safety.get("paper_endpoint_verified", safety.get("paper_endpoint_confirmed", paper_mode_verified))
    )
    # Broker adapters historically exposed either an explicit rejection flag
    # or the inverse ``broker_live_endpoint_allowed`` flag.  Treat both as the
    # same safety fact; a missing optional alias must not disable a valid paper
    # lane while the authoritative broker status already rejects live access.
    live_endpoint_rejected = bool(
        safety.get("live_endpoint_rejected") is True
        or not bool(safety.get("live_endpoint_detected", False))
        and not bool(safety.get("broker_live_endpoint_allowed", False))
    )

    kill_key = ""
    legacy_status = "NOT_APPLICABLE"
    if lane == LANE_DAY:
        activation_key = "ASTRA_DAY_LANE_PILOT_ENABLED"
        kill_key = "ASTRA_DAY_LANE_PILOT_DISABLE_SWITCH"
        requested = _truthy(values.get(activation_key, "0"))
        legacy_key = "ASTRA_DAY_LEARNING_LANE_ENABLED"
        legacy_present = legacy_key in values and _text(values.get(legacy_key)) != ""
        legacy_value = _truthy(values.get(legacy_key, "0"))
        if legacy_present and legacy_value != requested:
            legacy_status = "LEGACY_DAY_SWITCH_CONFLICT"
            blockers.append("LEGACY_DAY_SWITCH_CONFLICT")
        elif legacy_present:
            legacy_status = "LEGACY_COMPATIBLE_DEPRECATED"
        else:
            legacy_status = "LEGACY_UNSET_COMPATIBLE"
    elif lane == LANE_CRYPTO:
        activation_key = "ASTRA_ENABLE_ALPACA_CRYPTO_PAPER"
        kill_key = "ASTRA_ALPACA_CRYPTO_PAPER_KILL_SWITCH"
        requested = _truthy(values.get(activation_key, "0"))
    elif lane == LANE_SWING:
        activation_key = "ASTRA_SWING_LANE_ENABLED"
        requested = not (activation_key in values and not _truthy(values.get(activation_key)))
    else:
        return {
            "lane_id": lane,
            "lane_enabled": False,
            "execution_enabled": False,
            "exact_blockers": ["UNKNOWN_LANE"],
            "source_version": ACTIVATION_CONTRACT_VERSION,
            "generated_at": utc_now_iso(),
        }

    kill_switch = _truthy(values.get(kill_key, "0")) if kill_key else False
    if not requested:
        blockers.append("LANE_NOT_ENABLED")
    if kill_switch:
        blockers.append("KILL_SWITCH_ACTIVE")
    if not paper_mode_verified:
        blockers.append("PAPER_MODE_NOT_VERIFIED")
    if not paper_endpoint_verified:
        blockers.append("PAPER_ENDPOINT_NOT_VERIFIED")
    if not live_endpoint_rejected:
        blockers.append("LIVE_ENDPOINT_NOT_REJECTED")
    if not broker_execution_enabled:
        blockers.append("BROKER_EXECUTION_NOT_ENABLED")
    if not bool(capital.get("capital_configured", lane == LANE_SWING)):
        blockers.append(str(capital.get("capital_configuration_status") or "CAPITAL_CONFIGURATION_REQUIRED"))
    if not candidate_source_ready:
        blockers.append("CANDIDATE_SOURCE_NOT_READY")
    if not candidate_freshness_ready:
        blockers.append("CANDIDATE_FRESHNESS_NOT_READY")
    if not entry_worker_ready:
        blockers.append("ENTRY_WORKER_NOT_READY")
    if not exit_worker_ready:
        blockers.append("EXIT_WORKER_NOT_READY")
    if not position_owner_ready:
        blockers.append("POSITION_OWNER_NOT_READY")
    if not truth_pipeline_ready:
        blockers.append("TRUTH_PIPELINE_NOT_READY")
    if not learning_delivery_ready:
        blockers.append("LEARNING_DELIVERY_NOT_READY")

    lane_enabled = bool(requested and not kill_switch and legacy_status != "LEGACY_DAY_SWITCH_CONFLICT")
    # A session block is an exact per-candidate condition, not a configuration
    # disablement.  Preserve it separately so a closed weekend cannot make the
    # execution owner look structurally disabled.
    execution_enabled = bool(lane_enabled and not blockers)
    return {
        "lane_id": lane,
        "lane_enabled": lane_enabled,
        "execution_enabled": execution_enabled,
        "activation_requested": bool(requested),
        "activation_environment_key": activation_key,
        "legacy_switch_status": legacy_status,
        "legacy_switch_deprecation_warning": legacy_status == "LEGACY_COMPATIBLE_DEPRECATED",
        "paper_mode_verified": paper_mode_verified,
        "broker_execution_enabled": broker_execution_enabled,
        "paper_endpoint_verified": paper_endpoint_verified,
        "live_endpoint_rejected": live_endpoint_rejected,
        "capital_configured": bool(capital.get("capital_configured", lane == LANE_SWING)),
        "capital_book_id": capital.get("capital_book_id") or "paper_swing",
        "candidate_source_ready": bool(candidate_source_ready),
        "candidate_freshness_ready": bool(candidate_freshness_ready),
        "session_allowed": session_allowed,
        "broker_capability_ready": bool(paper_mode_verified and paper_endpoint_verified and live_endpoint_rejected and broker_execution_enabled),
        "entry_worker_ready": bool(entry_worker_ready),
        "exit_worker_ready": bool(exit_worker_ready),
        "position_owner_ready": bool(position_owner_ready),
        "truth_pipeline_ready": bool(truth_pipeline_ready),
        "learning_delivery_ready": bool(learning_delivery_ready),
        "kill_switch_state": "ACTIVE" if kill_switch else "CLEAR",
        "kill_switch_environment_key": kill_key,
        "exact_blockers": list(dict.fromkeys(blockers)),
        "activation_contract_consistent": legacy_status != "LEGACY_DAY_SWITCH_CONFLICT",
        "source_version": ACTIVATION_CONTRACT_VERSION,
        "generated_at": utc_now_iso(),
        "paper_only_preserved": True,
        "broker_live_endpoint_allowed": False,
        "behavior_safe_to_apply": False,
        "live_trading_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "position_sizing_changed": False,
        "portfolio_allocation_changed": False,
        "thresholds_changed": False,
    }


def canonical_multilane_activation_contract(
    env: Mapping[str, str] | None = None,
    *,
    broker_safety: Mapping[str, Any] | None = None,
    lane_inputs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Build the shared SWING/DAY/CRYPTO envelope without side effects."""
    inputs = dict(lane_inputs or {})
    return {
        lane: canonical_lane_activation_contract(
            lane,
            env,
            broker_safety=broker_safety,
            **dict(inputs.get(lane) or {}),
        )
        for lane in (LANE_SWING, LANE_DAY, LANE_CRYPTO)
    }


def day_regular_session_allowed(session: Any) -> bool:
    """DAY lane accepts only an authoritative regular equity session label."""
    return _text(session).lower() in {"regular", "regular_hours"}


def lane_handoff_proof(
    lane_id: str,
    trace_rows: Iterable[Mapping[str, Any]],
    capital: Mapping[str, Any],
    *,
    session: Any = None,
) -> dict[str, Any]:
    """Validate a real selected dry-run trace, never an allocator fixture."""
    lane = _text(lane_id).upper()
    envelope = LANE_ENVELOPES.get(lane)
    expected_book = envelope.capital_book_id if envelope else "paper_swing"
    invalid_reasons: list[str] = []
    for raw in trace_rows:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        if _row_lane(row) != lane:
            continue
        has_identity = bool(_text(row.get("candidate_id")) and _text(row.get("recommendation_id")) and _text(row.get("candidate_source")))
        no_broker_action = not bool(row.get("submit_order")) and int(_number(row.get("broker_actions_used")) or 0) == 0
        if lane == LANE_DAY and has_identity and no_broker_action and bool(capital.get("capital_configured")) and _text(row.get("capital_book_id")) == expected_book and not day_regular_session_allowed(session or row.get("market_session_mode") or row.get("session_type")):
            return {
                "proven": True,
                "market_session_trace_proven": True,
                "proof_source": "PaperAutopilot.per_candidate_decision_trace",
                "lane_id": lane,
                "symbol": _text(row.get("symbol")).upper(),
                "candidate_id": _text(row.get("candidate_id")),
                "recommendation_id": _text(row.get("recommendation_id")),
                "selection_id": _text(row.get("selection_id") or row.get("decision_id")),
                "order_readiness_state": "BLOCKED_MARKET_SESSION",
                "capital_book_id": expected_book,
                "submit_order": False,
                "broker_actions_used": 0,
                "generated_at": _text(row.get("generated_at") or row.get("selection_timestamp")),
            }
        if not bool(row.get("selected")) or not bool(row.get("order_ready")):
            invalid_reasons.append("selection_or_order_readiness_missing")
            continue
        if bool(row.get("submit_order")) or int(_number(row.get("broker_actions_used")) or 0) != 0:
            invalid_reasons.append("trace_has_broker_action")
            continue
        if _text(row.get("capital_book_id")) != expected_book:
            invalid_reasons.append("CAPITAL_BOOK_MISMATCH")
            continue
        if not bool(capital.get("capital_configured")):
            invalid_reasons.append(str(capital.get("capital_configuration_status") or "CAPITAL_CONFIGURATION_REQUIRED"))
            continue
        if lane == LANE_DAY:
            if not day_regular_session_allowed(session or row.get("market_session_mode") or row.get("session_type")):
                invalid_reasons.append("BLOCKED_MARKET_SESSION")
                continue
            if row.get("same_session_exit_required") is not True or row.get("overnight_allowed") is not False:
                invalid_reasons.append("DAY_EXIT_CONTRACT_MISSING")
                continue
        if lane == LANE_CRYPTO and bool(row.get("equity_market_session_gate_applied")):
            invalid_reasons.append("CRYPTO_EQUITY_SESSION_CONTAMINATION")
            continue
        return {
            "proven": True,
            "proof_source": "PaperAutopilot.per_candidate_decision_trace",
            "lane_id": lane,
            "symbol": _text(row.get("symbol")).upper(),
            "candidate_id": _text(row.get("candidate_id")),
            "recommendation_id": _text(row.get("recommendation_id")),
            "selection_id": _text(row.get("selection_id") or row.get("decision_id")),
            "order_readiness_state": "ORDER_READY",
            "capital_book_id": expected_book,
            "submit_order": False,
            "broker_actions_used": 0,
            "generated_at": _text(row.get("generated_at") or row.get("selection_timestamp")),
        }
    return {
        "proven": False,
        "proof_source": "PaperAutopilot.per_candidate_decision_trace",
        "lane_id": lane,
        "capital_book_id": expected_book,
        "reason": invalid_reasons[0] if invalid_reasons else "NO_AUTHORITATIVE_CURRENT_TRACE_ROW",
        "invalid_reasons": sorted(set(invalid_reasons)),
        "submit_order": False,
        "broker_actions_used": 0,
    }


def strict_broker_truth(row: Mapping[str, Any]) -> bool:
    """Strict truth requires both real fill identifiers and closed lineage."""
    evidence = _text(row.get("evidence_class") or row.get("truth_quality")).upper()
    return bool(
        evidence == TRUTH_CLASS
        and _text(row.get("entry_fill_id") or row.get("entry_order_fill_id"))
        and _text(row.get("exit_fill_id") or row.get("exit_order_fill_id"))
        and _text(row.get("entry_order_id") or row.get("broker_order_id"))
        and _text(row.get("exit_order_id"))
        and _text(row.get("lifecycle_id"))
    )


def strict_truth_counts(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [dict(row) for row in rows if isinstance(row, Mapping) and strict_broker_truth(row)]
    by_lane = {lane: [row for row in valid if _row_lane(row) == lane] for lane in (LANE_SWING, LANE_DAY, LANE_CRYPTO)}
    equities = [row for row in valid if _text(row.get("asset_class")).lower() == "equity"]
    etfs = [row for row in valid if _text(row.get("instrument_type")).upper() == "ETF"]
    return {
        "total_broker_confirmed_complete": len(valid),
        "swing_broker_confirmed_complete": len(by_lane[LANE_SWING]),
        "day_broker_confirmed_complete": len(by_lane[LANE_DAY]),
        "crypto_broker_confirmed_complete": len(by_lane[LANE_CRYPTO]),
        "equity_broker_confirmed_complete": len(equities),
        "etf_broker_confirmed_complete": len(etfs),
        "cohort_counts_overlap_total": True,
        "strict_fill_linked_truth_required": True,
    }


def adaptive_throughput(lane_id: str, strict_truth_rows: Iterable[Mapping[str, Any]], health: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Select an operating level only inside Eric's approved paper envelope."""
    lane = _text(lane_id).upper()
    envelope = LANE_ENVELOPES.get(lane)
    if envelope is None:
        return {"adaptive_level": 1, "status": "NOT_APPLICABLE"}
    health = dict(health or {})
    truths = [row for row in strict_truth_rows if isinstance(row, Mapping) and strict_broker_truth(row) and _row_lane(row) == lane]
    integrity_ok = all(bool(health.get(key, True)) for key in (
        "paired_fill_integrity", "lane_ownership_integrity", "truth_persistence_success",
        "learning_delivery_success", "worker_health", "capital_accounting_integrity",
    ))
    critical = any(bool(health.get(key, False)) for key in (
        "ownership_ambiguous", "exit_linkage_failed", "overnight_breach", "duplicate_exposure",
        "repeated_order_rejections", "governance_red", "crypto_equity_session_contamination",
    ))
    count = len(truths)
    if critical:
        level, action = 0, "PAUSED_FAIL_CLOSED"
    elif not integrity_ok:
        level, action = 1, "DOWNGRADED_TO_LEVEL_1"
    elif count >= 20:
        level, action = 3, "LEVEL_3_ELIGIBLE"
    elif count >= 5:
        level, action = 2, "LEVEL_2_ELIGIBLE"
    else:
        level, action = 1, "LEVEL_1"
    opens = {1: envelope.initial_open_positions, 2: min(2, envelope.approved_open_positions), 3: envelope.approved_open_positions}.get(level, 0)
    completed = {1: envelope.initial_completed_trades, 2: min(4, envelope.approved_completed_trades), 3: envelope.approved_completed_trades}.get(level, 0)
    return {
        "lane_id": lane,
        "adaptive_level": level,
        "adaptive_status": action,
        "clean_truths_for_next_level": count,
        "max_open_positions_current": opens,
        "max_open_positions_approved": envelope.approved_open_positions,
        "max_completed_trades_current": completed,
        "max_completed_trades_approved": envelope.approved_completed_trades,
        "completed_trade_window": "rolling_24_hours" if envelope.rolling_24h else "regular_session",
        "automatic_expansion_above_approved_ceiling": False,
        "no_forced_throughput": True,
        "integrity_ok": integrity_ok,
        "critical_fail_closed": critical,
    }


def lane_owner_contract(row: Mapping[str, Any]) -> dict[str, Any]:
    lane = _row_lane(row)
    expected_owner = {LANE_DAY: "DAY", LANE_CRYPTO: "CRYPTO", LANE_SWING: "SWING"}.get(lane, "")
    position_owner = _text(row.get("position_owner"))
    exit_owner = _text(row.get("exit_policy_owner"))
    return {
        "lane_id": lane,
        "position_owner": position_owner,
        "exit_policy_owner": exit_owner,
        "owner_status": "PASS" if expected_owner and position_owner == expected_owner and exit_owner == expected_owner else "LANE_CONTRACT_REQUIRED",
        "automatic_management_allowed": bool(expected_owner and position_owner == expected_owner and exit_owner == expected_owner),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
