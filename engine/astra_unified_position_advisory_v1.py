"""Canonical advisory arbitration plus worker-owned current-position projection.

The original ``unified_position_recommendation`` remains the only policy
arbiter.  The V1 projection below persists its output for every current broker
position; it does not add an execution path or a second recommendation policy.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "astra_unified_position_advisory_v1"
LANE_EXIT_READINESS_FUNNEL_VERSION = "LANE_EXIT_READINESS_FUNNEL_V1"
LANE_EXIT_HISTORY_WINDOWS = {"SCALP": 3, "DAY": 5, "SWING": 8}
MAX_LANE_EXIT_HISTORY = 80
UNIFIED_PRECEDENCE = [
    "DATA_INCOMPLETE_FAIL_CLOSED", "UNRESOLVED_FAIL_CLOSED", "HARD_BOUNDARY_BREACH",
    "THESIS_BROKEN", "MANDATORY_REVIEW", "EXIT_REVIEW", "PROTECT_PROFIT",
    "RECOVERY_WATCH", "WATCH", "HOLD",
]


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _text(value: Any, default: str = "") -> str:
    return str(value or default).strip()


def _num(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_num(*values: Any) -> float | None:
    for value in values:
        if value not in (None, ""):
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def _lane(recovered: Mapping[str, Any], legacy: Mapping[str, Any]) -> str:
    value = _text(recovered.get("lane") or recovered.get("lane_id") or legacy.get("lane_id")).upper()
    return value if value in LANE_EXIT_HISTORY_WINDOWS else ""


def _has_state(value: Any, *states: str) -> bool:
    text = _text(value).upper()
    return any(state in text for state in states)


def _previous_exit_history(previous: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    funnel = dict((previous or {}).get("lane_exit_readiness_funnel_v1") or {})
    return {
        str(key): dict(value)
        for key, value in dict(funnel.get("position_history") or {}).items()
        if isinstance(value, Mapping)
    }


def _lane_exit_factors(
    item: Mapping[str, Any], legacy: Mapping[str, Any], loss: Mapping[str, Any], profit: Mapping[str, Any],
    resolution: Mapping[str, Any], recommendation: str,
) -> dict[str, Any]:
    """Normalize only existing advisory evidence; this has no order authority."""
    momentum = _text(item.get("momentum_status") or legacy.get("momentum_state"), "UNAVAILABLE").upper()
    profit_state = _text(profit.get("canonical_recommendation") or profit.get("profit_state"), "UNAVAILABLE").upper()
    loss_state = _text(loss.get("canonical_recommendation") or loss.get("threshold_state"), "UNAVAILABLE").upper()
    thesis = _text(profit.get("thesis_state") or loss.get("thesis_state") or legacy.get("thesis_state") or item.get("thesis_state"), "UNAVAILABLE").upper()
    opportunity = _text(item.get("opportunity_cost_status"), "UNAVAILABLE").upper()
    replacement = _text(item.get("replacement_candidate_status"), "UNAVAILABLE").upper()
    remaining_upside = _optional_num(resolution.get("remaining_expected_upside_pct"), legacy.get("remaining_expected_upside_pct"), profit.get("remaining_expected_upside_pct"))
    remaining_downside = _optional_num(resolution.get("remaining_expected_downside_pct"), legacy.get("remaining_expected_downside_pct"), loss.get("remaining_expected_downside_pct"))
    return_per_time = _optional_num(resolution.get("return_per_hour"), legacy.get("return_per_hour"), item.get("return_per_hour"))
    reasons: list[str] = []
    score = 0.0
    thesis_broken = _has_state(thesis, "THESIS_BROKEN") or _has_state(profit_state, "THESIS_BROKEN")
    if thesis_broken:
        score, reasons = 100.0, ["EXISTING_THESIS_BROKEN"]
    else:
        if _has_state(recommendation, "EXIT_REVIEW") or _has_state(profit_state, "EXIT_REVIEW"):
            score += 45.0; reasons.append("EXISTING_EXIT_REVIEW")
        elif _has_state(profit_state, "PROTECT_PROFIT"):
            score += 25.0; reasons.append("EXISTING_PROFIT_PROTECTION")
        if _has_state(momentum, "DETERIORATING", "FAILING", "WEAKENING"):
            score += 15.0; reasons.append("MOMENTUM_DETERIORATING")
        if _has_state(loss_state, "WATCH", "REVIEW", "THESIS_BROKEN"):
            score += 15.0; reasons.append("EXISTING_LOSS_CONTAINMENT")
        if remaining_upside is not None and remaining_downside is not None and abs(remaining_downside) >= max(remaining_upside, 0.0):
            score += 10.0; reasons.append("REMAINING_ASYMMETRY_WEAK")
        if return_per_time is not None and return_per_time <= 0.0:
            score += 8.0; reasons.append("RETURN_PER_TIME_WEAK")
    weakening = score > 0.0
    replacement_pressure = _has_state(opportunity, "HIGH", "OPPORTUNITY_COST") or _has_state(replacement, "AVAILABLE", "STRONGER")
    if replacement_pressure:
        reasons.append("REPLACEMENT_PRESSURE" if weakening else "REPLACEMENT_OBSERVED")
        if weakening:
            score += 8.0
    return {
        "score": min(100.0, round(score, 4)), "reason_codes": reasons, "replacement_pressure": replacement_pressure,
        "thesis_health": "THESIS_BROKEN" if thesis_broken else "THESIS_WEAKENING" if weakening else "THESIS_HEALTHY" if momentum in {"IMPROVING", "STABLE"} else "UNAVAILABLE",
        "profit_giveback_pressure": "HIGH" if _has_state(profit_state, "EXIT_REVIEW", "THESIS_BROKEN") else "MODERATE" if _has_state(profit_state, "PROTECT_PROFIT") else "UNAVAILABLE",
        "opportunity_cost_pressure": "ELEVATED" if replacement_pressure and weakening else "OBSERVED" if replacement_pressure else "UNAVAILABLE",
        "remaining_upside_pct": remaining_upside, "remaining_downside_pct": remaining_downside, "return_per_time": return_per_time,
    }


def _lane_exit_state(lane: str, position_id: str, factors: Mapping[str, Any], recommendation: str, previous: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    prior = dict((previous or {}).get(position_id) or {})
    history = [dict(row) for row in list(prior.get("history") or []) if isinstance(row, Mapping)]
    score = _num(factors.get("score"))
    immediate_thesis_break = _has_state(factors.get("thesis_health"), "THESIS_BROKEN")
    immediate_review = _has_state(recommendation, "EXIT_REVIEW")
    provisional = "THESIS_BROKEN" if immediate_thesis_break else "EXIT_REVIEW" if immediate_review else "PROTECT_PROFIT" if _has_state(factors.get("profit_giveback_pressure"), "MODERATE", "HIGH") else "WATCH" if score > 0.0 else "HOLD"
    history.append({"observed_at": _now(), "score": score, "state": provisional})
    history = history[-LANE_EXIT_HISTORY_WINDOWS[lane]:]
    weakening_states = {"WATCH", "PROTECT_PROFIT", "EXIT_REVIEW"}
    consecutive = 0
    for row in reversed(history):
        if _text(row.get("state")).upper() not in weakening_states:
            break
        consecutive += 1
    average = round(sum(_num(row.get("score")) for row in history) / len(history), 4) if history else 0.0
    persistent = consecutive >= min(2, LANE_EXIT_HISTORY_WINDOWS[lane])
    if immediate_thesis_break:
        state = "THESIS_BROKEN"
    elif immediate_review:
        state = "EXIT_REVIEW"
    elif factors.get("replacement_pressure") and persistent and score > 0.0:
        state = "REPLACE_CANDIDATE"
    elif provisional == "PROTECT_PROFIT" and persistent and score >= 40.0:
        state = "EXIT_REVIEW"
    elif provisional == "PROTECT_PROFIT":
        state = "PROTECT_PROFIT"
    elif persistent and average >= 20.0:
        state = "EXIT_REVIEW"
    elif score > 0.0:
        state = "WATCH"
    else:
        state = "HOLD"
    observed_at = history[-1]["observed_at"]
    record = {
        "lane": lane, "history": history,
        "first_watch_at": prior.get("first_watch_at") or (observed_at if state == "WATCH" else None),
        "first_protect_profit_at": prior.get("first_protect_profit_at") or (observed_at if state == "PROTECT_PROFIT" else None),
        "first_exit_review_at": prior.get("first_exit_review_at") or (observed_at if state in {"EXIT_REVIEW", "REPLACE_CANDIDATE"} else None),
    }
    return {
        "lane_exit_readiness_score": score, "lane_exit_readiness_state": state,
        "exit_persistence_state": "PERSISTENT_DETERIORATION" if persistent else "TEMPORARY_NOISE" if score > 0.0 else "STABLE_HEALTH",
        "exit_persistence_observations": len(history), "exit_recent_average_score": average,
        "consecutive_weakening_cycles": consecutive, "exit_reason_codes": list(factors.get("reason_codes") or []),
        "profit_giveback_pressure": factors.get("profit_giveback_pressure"), "thesis_health": factors.get("thesis_health"),
        "opportunity_cost_pressure": factors.get("opportunity_cost_pressure"), "remaining_upside_pct": factors.get("remaining_upside_pct"),
        "remaining_downside_pct": factors.get("remaining_downside_pct"), "return_per_time": factors.get("return_per_time"),
        "exit_execution_authority": "DISABLED", "exit_advisory_only": True,
    }, record


def unified_position_recommendation(
    loss_containment: Mapping[str, Any] | None = None,
    profit_protection: Mapping[str, Any] | None = None,
    peak_memory_entry: Mapping[str, Any] | None = None,
    ownership: str = "UNKNOWN",
    thesis_broken: bool = False,
    support_failed: bool = False,
    stale_evidence: bool = False,
    unresolved: bool = False,
) -> dict[str, Any]:
    """Original deterministic policy arbiter; always advisory-only."""
    lc, pp, peak = dict(loss_containment or {}), dict(profit_protection or {}), dict(peak_memory_entry or {})
    recommendation, rationale, state, confidence = "HOLD", [], "HEALTHY", 0.65
    if unresolved or ownership == "UNRESOLVED_FAIL_CLOSED":
        recommendation, rationale, state, confidence = "DATA_INCOMPLETE_FAIL_CLOSED", ["unresolved_ownership"], "UNRESOLVED_FAIL_CLOSED", 0.95
    elif stale_evidence:
        recommendation, rationale, state, confidence = "DATA_INCOMPLETE_FAIL_CLOSED", ["stale_critical_evidence"], "UNRESOLVED_FAIL_CLOSED", 0.95
    elif "HARD_BOUNDARY_BREACH" in _text(lc.get("threshold_state")).upper():
        recommendation, rationale, state, confidence = "HARD_BOUNDARY_BREACH", [f"hard_loss_boundary: {_text(lc.get('canonical_recommendation'))}"], "HARD_BOUNDARY_BREACH", 0.95
    elif thesis_broken or "THESIS_BROKEN" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "THESIS_BROKEN", ["thesis_explicitly_broken"], "THESIS_BROKEN", 0.85
    elif "MANDATORY_REVIEW" in _text(lc.get("threshold_state")).upper() or "EXIT_REVIEW" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "EXIT_REVIEW", ["existing_protection_review"], "MANDATORY_REVIEW", 0.80
    elif "PROTECT_PROFIT" in _text(pp.get("profit_state")).upper():
        recommendation, rationale, state, confidence = "PROTECT_PROFIT", ["profit_protection"], "PROTECT_PROFIT", 0.70
    elif support_failed:
        recommendation, rationale, state, confidence = "WATCH", ["support_failure_watch"], "WATCH", 0.60
    else:
        current_return = _num(peak.get("current_return_pct"), 0.0)
        giveback = peak.get("giveback_ratio")
        if isinstance(giveback, (int, float)) and giveback > 0.50:
            recommendation, rationale, state, confidence = "EXIT_REVIEW", [f"severe_giveback: {giveback:.2f}"], "EXIT_REVIEW", 0.75
        elif current_return < -20.0:
            recommendation, rationale, state, confidence = "EXIT_REVIEW", [f"severe_loss: {current_return:.1f}%"], "EXIT_REVIEW", 0.80
        elif current_return < -10.0:
            recommendation, rationale, state, confidence = "WATCH", [f"moderate_loss: {current_return:.1f}%"], "WATCH", 0.65
        else:
            rationale = ["position_within_tolerance"]
    return {"canonical_recommendation": recommendation, "unified_state": state, "unified_rationale": "; ".join(rationale),
            "confidence": round(confidence, 4), "advisory_only": True, "execution_authorized": False,
            "evidence_completeness": "incomplete" if (stale_evidence or unresolved) else "sufficient"}


def _index(rows: list[Mapping[str, Any]] | None) -> dict[str, dict[str, Any]]:
    return {_text(row.get("symbol")).upper(): dict(row) for row in rows or [] if isinstance(row, Mapping) and _text(row.get("symbol"))}


def _decisions_by_position_id(state: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Index decisions only by the Astra canonical position identity.

    A broker asset identifier and an Astra lifecycle identifier are different
    namespaces.  Symbol indexing can also select a retired same-symbol
    decision after a new entry, so it is intentionally prohibited here.
    """
    decisions = dict((state or {}).get("decisions") or {})
    indexed: dict[str, dict[str, Any]] = {}
    for decision in decisions.values():
        if not isinstance(decision, Mapping):
            continue
        position_id = _text(decision.get("position_id"))
        if position_id:
            indexed[position_id] = dict(decision)
    return indexed


def _recovery_by_symbol(recovery: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    return _index(list((recovery or {}).get("positions") or []))


def _canonical_same_session_requirement(recovered: Mapping[str, Any] | None) -> dict[str, Any]:
    """Expose a proven hard horizon term without creating an exit authority."""
    row = dict(recovered or {})
    required = (
        _text(row.get("canonical_identity_status")).upper() == "RESOLVED"
        and _text(row.get("horizon_contract_status")).upper() == "RESOLVED"
        and row.get("same_session_exit_required") is True
        and row.get("overnight_allowed") is False
        and _text(row.get("expected_max_hold")).lower() == "same_session"
    )
    return {
        "status": "CANONICAL_SAME_SESSION_EXIT_REQUIRED" if required else "UNAVAILABLE",
        "same_session_exit_required": True if required else None,
        "overnight_allowed": False if required else None,
        "expected_max_hold": "same_session" if required else None,
        "source": "astra_position_lane_horizon_recovery_v1" if required else "UNAVAILABLE",
    }


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, sort_keys=True, separators=(",", ":"))
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try: os.unlink(temporary)
        except OSError: pass
        raise


def build_unified_position_advisory_v1(
    broker_positions: Mapping[str, Mapping[str, Any]], *, evidence: Mapping[str, Any], triage: Mapping[str, Any],
    loss_containment: Mapping[str, Any] | None = None, profit_protection: Mapping[str, Any] | None = None,
    exit_readiness: Mapping[str, Any] | None = None, resolution: Mapping[str, Any] | None = None,
    shadow_handoff: Mapping[str, Mapping[str, Any]] | None = None,
    recovery: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    evidence_by_symbol = _index(list(evidence.get("positions") or []))
    triage_by_symbol = _index(list(triage.get("positions") or []))
    loss_by_position_id = _decisions_by_position_id(loss_containment)
    profit_by_position_id = _decisions_by_position_id(profit_protection)
    exit_by_symbol = _index(list((exit_readiness or {}).get("positions") or []))
    resolution_by_symbol = _index(list((resolution or {}).get("positions") or []))
    recovery_by_symbol = _recovery_by_symbol(recovery)
    rows = []
    for symbol in sorted(broker_positions or {}):
        evidence_row, triage_row = evidence_by_symbol.get(symbol, {}), triage_by_symbol.get(symbol, {})
        recovered = recovery_by_symbol.get(symbol, {})
        canonical_position_id = _text(recovered.get("canonical_position_id"))
        canonical_identity_status = _text(recovered.get("canonical_identity_status")) or "UNAVAILABLE"
        # Missing or ambiguous identity must not select another lifecycle's
        # risk decision.  The policy below remains fail-closed in that case.
        loss = loss_by_position_id.get(canonical_position_id, {}) if canonical_identity_status == "RESOLVED" else {}
        profit = profit_by_position_id.get(canonical_position_id, {}) if canonical_identity_status == "RESOLVED" else {}
        resolution_row = resolution_by_symbol.get(symbol, {})
        shadow = dict((shadow_handoff or {}).get(symbol) or {})
        # A legacy triage overlay is evidence, not an identity owner.  An
        # exact current lifecycle must never be downgraded merely because a
        # same-symbol legacy row also exists.
        legacy = bool(triage_row) and canonical_identity_status != "RESOLVED"
        policy = unified_position_recommendation(
            loss, profit, ownership="UNRESOLVED_FAIL_CLOSED" if evidence_row.get("canonical_lane_status") != "RESOLVED" and not legacy else "KNOWN",
            stale_evidence=evidence_row.get("quote_status") == "STALE" or evidence_row.get("completed_bar_status") == "STALE",
        )
        exit_row = exit_by_symbol.get(symbol, {})
        horizon_requirement = _canonical_same_session_requirement(recovered)
        generic_recommendation = _text(exit_row.get("generic_recommendation")) or _text(exit_row.get("recommendation")) or _text(triage_row.get("recommendation")) or _text(policy.get("canonical_recommendation")) or "WATCH"
        recommendation = "SAME_SESSION_EXIT_REQUIRED" if horizon_requirement["status"] == "CANONICAL_SAME_SESSION_EXIT_REQUIRED" else generic_recommendation
        blocker = _text(exit_row.get("first_causal_blocker")) or _text(triage_row.get("first_causal_blocker")) or _text(evidence_row.get("first_causal_blocker")) or _text((loss.get("exact_blockers") or [""])[0]) or "EVIDENCE_UNAVAILABLE"
        confidence = _text(triage_row.get("confidence")) or _text(loss.get("confidence")) or _text(evidence_row.get("evidence_confidence")) or "LOW"
        rows.append({
            "symbol": symbol,
            "canonical_position_id": canonical_position_id or None,
            "lifecycle_id": canonical_position_id or None,
            "canonical_identity_status": canonical_identity_status,
            "final_advisory": recommendation, "generic_advisory": generic_recommendation, "confidence": confidence,
            "priority": "HIGH" if recommendation in {"EXIT_REVIEW", "THESIS_BROKEN", "PROTECT_CAPITAL", "SAME_SESSION_EXIT_REQUIRED"} else "MEDIUM" if recommendation == "WATCH" else "LOW",
            "primary_reason": "canonical same-session horizon requires existing exit-policy review" if horizon_requirement["status"] == "CANONICAL_SAME_SESSION_EXIT_REQUIRED" else (_text(resolution_row.get("plain_english_explanation")) or _text(triage_row.get("plain_english_reason")) or _text(loss.get("human_readable_reason")) or blocker),
            "supporting_reasons": [blocker], "evidence_used": triage_row.get("evidence_used") or {},
            "evidence_missing": triage_row.get("evidence_missing") or ([blocker] if blocker != "EVIDENCE_CURRENT" else []),
            "first_causal_blocker": blocker, "source_components": [name for name, row in (("position_evidence_completeness_v1", evidence_row), ("legacy_position_risk_triage_v1", triage_row), ("legacy_position_resolution_v1", resolution_row), ("exit_readiness", exit_row), ("loss_containment", loss), ("profit_protection", profit)) if row],
            "legacy_position": legacy, "loss_containment_state": loss.get("canonical_recommendation"), "profit_protection_state": profit.get("canonical_recommendation") or profit.get("profit_state"),
            "resolution_plan": resolution_row.get("resolution_plan"), "capacity_impact": resolution_row.get("estimated_capacity_releasable"), "urgency": resolution_row.get("urgency"),
            "horizon_exit_requirement": horizon_requirement,
            **shadow,
            "shadow_only": True, "promotion_status": "NOT_PROMOTED",
            "generated_at": _now(), "execution_authority": "DISABLED", "advisory_only": True,
        })
    return {"schema_version": SCHEMA_VERSION, "generated_at": _now(), "broker_position_count": len(broker_positions or {}), "advisory_count": len(rows), "positions": rows,
            "silent_drop_count": max(0, len(broker_positions or {}) - len(rows)), "execution_authority": "DISABLED", "advisory_only": True,
            "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0, "state_mutations_from_get": 0, "paper_only_preserved": True}


def build_position_exit_readiness_v1(
    broker_positions: Mapping[str, Mapping[str, Any]], *, evidence: Mapping[str, Any], triage: Mapping[str, Any],
    loss_containment: Mapping[str, Any] | None = None, profit_protection: Mapping[str, Any] | None = None,
    resolution: Mapping[str, Any] | None = None,
    shadow_handoff: Mapping[str, Mapping[str, Any]] | None = None,
    recovery: Mapping[str, Any] | None = None,
    previous_exit_readiness: Mapping[str, Any] | None = None,
    include_lane_exit_funnel: bool = False,
) -> dict[str, Any]:
    """Persist the existing advisory policy inputs for every broker position.

    This is not an order authorization state machine.  It records whether the
    existing human-review recommendation has current evidence and keeps the
    first missing producer visible to the later unified advisory.
    """
    evidence_by_symbol = _index(list(evidence.get("positions") or []))
    triage_by_symbol = _index(list(triage.get("positions") or []))
    loss_by_symbol = _index(list((loss_containment or {}).get("decisions", {}).values()))
    profit_by_symbol = _index(list((profit_protection or {}).get("decisions", {}).values()))
    resolution_by_symbol = _index(list((resolution or {}).get("positions") or []))
    recovery_by_symbol = _recovery_by_symbol(recovery)
    previous_history = _previous_exit_history(previous_exit_readiness) if include_lane_exit_funnel else {}
    position_history: dict[str, dict[str, Any]] = {}
    lane_rows: dict[str, list[dict[str, Any]]] = {lane: [] for lane in LANE_EXIT_HISTORY_WINDOWS}
    rows = []
    for symbol in sorted(broker_positions or {}):
        item, legacy, loss, profit = evidence_by_symbol.get(symbol, {}), triage_by_symbol.get(symbol, {}), loss_by_symbol.get(symbol, {}), profit_by_symbol.get(symbol, {})
        resolution_row = resolution_by_symbol.get(symbol, {})
        recovered = recovery_by_symbol.get(symbol, {})
        shadow = dict((shadow_handoff or {}).get(symbol) or {})
        policy = unified_position_recommendation(loss, profit, ownership="KNOWN", stale_evidence=item.get("quote_status") == "STALE" or item.get("completed_bar_status") == "STALE")
        horizon_requirement = _canonical_same_session_requirement(recovered)
        generic_recommendation = _text(legacy.get("recommendation")) or _text(policy.get("canonical_recommendation")) or "WATCH"
        recommendation = "SAME_SESSION_EXIT_REQUIRED" if horizon_requirement["status"] == "CANONICAL_SAME_SESSION_EXIT_REQUIRED" else generic_recommendation
        blocker = _text(legacy.get("first_causal_blocker")) or _text(item.get("first_causal_blocker")) or "EVIDENCE_UNAVAILABLE"
        row = {
            "symbol": symbol, "exit_readiness_state": "CANONICAL_SAME_SESSION_EXIT_REQUIRED" if horizon_requirement["status"] == "CANONICAL_SAME_SESSION_EXIT_REQUIRED" else ("EVIDENCE_INCOMPLETE" if blocker != "EVIDENCE_CURRENT" else "ADVISORY_READY"),
            "recommendation": recommendation, "generic_recommendation": generic_recommendation, "confidence": _text(legacy.get("confidence")) or _text(policy.get("confidence")) or "LOW",
            "urgency": "HIGH" if recommendation in {"EXIT_REVIEW", "THESIS_BROKEN", "PROTECT_CAPITAL", "SAME_SESSION_EXIT_REQUIRED"} else "MEDIUM" if recommendation == "WATCH" else "LOW",
            "forward_value_state": _text(item.get("opportunity_cost_status")) or "MISSING", "risk_state": _text(loss.get("canonical_recommendation")) or "UNAVAILABLE",
            "profit_protection_state": _text(profit.get("canonical_recommendation") or profit.get("profit_state")) or "UNAVAILABLE",
            "legacy_triage_state": _text(legacy.get("recommendation")) or "NOT_APPLICABLE", "opportunity_cost_state": _text(item.get("opportunity_cost_status")) or "MISSING",
            "replacement_state": _text(item.get("replacement_candidate_status")) or "MISSING", "evidence_used": legacy.get("evidence_used") or {},
            "evidence_missing": legacy.get("evidence_missing") or ([blocker] if blocker != "EVIDENCE_CURRENT" else []), "first_causal_blocker": blocker,
            "plain_english_reason": _text(resolution_row.get("plain_english_explanation")) or _text(legacy.get("plain_english_reason")) or blocker.lower().replace("_", " "),
            "resolution_plan": resolution_row.get("resolution_plan"), "capacity_impact": resolution_row.get("estimated_capacity_releasable"),
            "canonical_position_id": recovered.get("canonical_position_id") if _text(recovered.get("canonical_identity_status")).upper() == "RESOLVED" else None,
            "canonical_identity_status": _text(recovered.get("canonical_identity_status")) or "UNAVAILABLE",
            "horizon_exit_requirement": horizon_requirement,
            **shadow,
            "shadow_only": True, "promotion_status": "NOT_PROMOTED",
            "execution_authority": "DISABLED", "advisory_only": True,
        }
        lane = _lane(recovered, legacy)
        position_id = _text(row.get("canonical_position_id"))
        if include_lane_exit_funnel and lane and position_id:
            factors = _lane_exit_factors(item, legacy, loss, profit, resolution_row, generic_recommendation)
            funnel_row, history = _lane_exit_state(lane, position_id, factors, generic_recommendation, previous_history)
            row.update(funnel_row)
            position_history[position_id] = history
            lane_rows[lane].append(row)
        rows.append(row)
    prior_funnel = dict((previous_exit_readiness or {}).get("lane_exit_readiness_funnel_v1") or {})
    cohort = dict(prior_funnel.get("prospective_cohort") or {})
    if include_lane_exit_funnel and not cohort:
        cohort = {
            "change_id": LANE_EXIT_READINESS_FUNNEL_VERSION,
            "activated_at": _now(),
            "scope": list(LANE_EXIT_HISTORY_WINDOWS),
            "mode": "paper_only_advisory_exit_evidence",
            "measurement_checkpoints": [10, 20, 30],
        }
    telemetry = {
        lane: {
            "open_positions": len(lane_rows[lane]),
            **{state: sum(_text(row.get("lane_exit_readiness_state")).upper() == state for row in lane_rows[lane]) for state in ("HOLD", "WATCH", "PROTECT_PROFIT", "EXIT_REVIEW", "REPLACE_CANDIDATE", "THESIS_BROKEN")},
            "average_exit_readiness": round(sum(_num(row.get("lane_exit_readiness_score")) for row in lane_rows[lane]) / len(lane_rows[lane]), 4) if lane_rows[lane] else None,
            "persistent_deterioration": sum(_text(row.get("exit_persistence_state")) == "PERSISTENT_DETERIORATION" for row in lane_rows[lane]),
            "high_giveback": sum(_text(row.get("profit_giveback_pressure")) == "HIGH" for row in lane_rows[lane]),
        }
        for lane in LANE_EXIT_HISTORY_WINDOWS
    }
    funnel = {
        "schema_version": LANE_EXIT_READINESS_FUNNEL_VERSION,
        "enabled": bool(include_lane_exit_funnel),
        "prospective_cohort": cohort if include_lane_exit_funnel else {},
        "history_windows": dict(LANE_EXIT_HISTORY_WINDOWS),
        "max_positions_per_lane": MAX_LANE_EXIT_HISTORY,
        "position_history": dict(list(position_history.items())[:MAX_LANE_EXIT_HISTORY * len(LANE_EXIT_HISTORY_WINDOWS)]),
        "lanes": telemetry,
        "execution_authority": "DISABLED", "advisory_only": True,
        "provider_calls_used": 0, "broker_actions_used": 0, "paper_only_preserved": True,
    }
    return {"schema_version": "astra_position_exit_readiness_v1", "generated_at": _now(), "broker_position_count": len(broker_positions or {}),
            "positions_reviewed": len(rows), "positions": rows, "silent_drop_count": max(0, len(broker_positions or {}) - len(rows)),
            "execution_authority": "DISABLED", "advisory_only": True, "provider_calls_used": 0, "broker_actions_used": 0, "llm_calls_used": 0,
            "state_mutations_from_get": 0, "paper_only_preserved": True,
            "lane_exit_readiness_funnel_v1": funnel}


def save_position_exit_readiness_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_position_exit_readiness_v1.json", payload)


def load_position_exit_readiness_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try: payload = json.loads((Path(state_dir) / "astra_position_exit_readiness_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return dict(payload) if isinstance(payload, dict) else {}


def save_unified_position_advisory_v1(payload: Mapping[str, Any], state_dir: str | Path = "state") -> None:
    _atomic_write(Path(state_dir) / "astra_unified_position_advisory_v1.json", payload)


def load_unified_position_advisory_v1(state_dir: str | Path = "state") -> dict[str, Any]:
    try: payload = json.loads((Path(state_dir) / "astra_unified_position_advisory_v1.json").read_text(encoding="utf-8"))
    except (OSError, ValueError): return {}
    return dict(payload) if isinstance(payload, dict) else {}
