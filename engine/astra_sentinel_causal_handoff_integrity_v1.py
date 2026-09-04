"""Bounded causal classification for the canonical Sentinel scanner.

This module is deliberately a pure classifier.  The worker supplies only
current, already-committed facts; it never reads providers, brokers, or raw
history and it cannot alter trading behavior.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable


VERSION = "2.0.0"
MAX_FACTS = 24
LANES = ("SCALP", "DAY", "SWING", "CRYPTO")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _unavailable(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "unknown", "unavailable", "missing", "none", "null", "n/a"})


def _signal(fact: dict[str, Any], *, kind: str, category: str, handoff: str, repair: str, severity: str = "HIGH") -> dict[str, Any]:
    return {
        "kind": kind,
        "monitor": fact.get("monitor"),
        "category": category,
        "severity": severity,
        "confidence": "VERIFIED",
        "canonical_fact_ids": [str(fact.get("field") or fact.get("fact") or kind)],
        "affected_components": [str(fact.get("producer") or "producer"), str(fact.get("consumer") or "consumer")],
        "first_bad_handoff": handoff,
        "owner": str(fact.get("owner") or fact.get("producer") or "canonical evidence owner"),
        "repair": repair,
        "downstream_symptoms": [str(fact.get("downstream_symptom") or kind)],
        "causal_finding_v1": {
            "category": category,
            "candidate_id": fact.get("candidate_id"),
            "lifecycle_id": fact.get("lifecycle_id"),
            "symbol": fact.get("symbol"),
            "lane": fact.get("lane"),
            "worker_generation_id": fact.get("worker_generation_id"),
            "producer": fact.get("producer"),
            "consumer": fact.get("consumer"),
            "field": fact.get("field"),
            "producer_state": fact.get("producer_state") or "AVAILABLE",
            "consumer_state": fact.get("consumer_state") or "UNAVAILABLE",
            "consumer_blocker": fact.get("consumer_blocker"),
            "first_incomplete_stage": fact.get("first_incomplete_stage"),
            "deadline_source": fact.get("deadline_source"),
            "first_bad_handoff": handoff,
            "current_vs_historical": "CURRENT",
            "legitimate_fail_closed": False,
            "evidence_timestamp": fact.get("evidence_timestamp"),
            "confidence": "VERIFIED",
            "smallest_safe_repair": repair,
            "runtime_verification_required": True,
        },
    }


def classify_causal_handoff_facts_v1(facts: list[dict[str, Any]] | None, *, limit: int = MAX_FACTS) -> dict[str, Any]:
    """Classify bounded producer/consumer facts without inferring evidence."""
    signals: list[dict[str, Any]] = []
    nondefects: list[dict[str, Any]] = []
    for raw in list(facts or [])[:max(1, int(limit))]:
        if not isinstance(raw, dict):
            continue
        fact = dict(raw)
        current = bool(fact.get("current", True))
        kind = _text(fact.get("kind")).upper()
        timestamp = fact.get("evidence_timestamp")
        base = {
            "category": "INSUFFICIENT_RUNTIME_EVIDENCE",
            "candidate_id": fact.get("candidate_id"),
            "lifecycle_id": fact.get("lifecycle_id"),
            "worker_generation_id": fact.get("worker_generation_id"),
            "producer": fact.get("producer"),
            "consumer": fact.get("consumer"),
            "field": fact.get("field"),
            "producer_state": fact.get("producer_state"),
            "consumer_state": fact.get("consumer_state"),
            "first_bad_handoff": None,
            "current_vs_historical": "CURRENT" if current else "HISTORICAL",
            "legitimate_fail_closed": False,
            "evidence_timestamp": timestamp,
            "confidence": "BOUNDED_RUNTIME_EVIDENCE",
            "smallest_safe_repair": None,
            "runtime_verification_required": False,
            "reason": "causal_handoff_insufficient_runtime_evidence",
        }
        if not current or kind == "HISTORICAL":
            nondefects.append({**base, "category": "STALE_OR_HISTORICAL_STATE_MISCLASSIFIED_CURRENT", "legitimate_fail_closed": True, "reason": "historical_evidence_not_current"})
        elif kind in {"STALE_NATIVE_QUOTE", "FORECAST_NOT_POSITIVE", "RISK_EVIDENCE_MISSING", "MARKET_SESSION_CLOSED", "CAPACITY_EXHAUSTED"}:
            nondefects.append({**base, "category": "LEGITIMATE_FAIL_CLOSED", "legitimate_fail_closed": True, "reason": kind.lower()})
        elif kind == "PLACEHOLDER_SHADOWING" or bool(fact.get("placeholder_used_as_measured")):
            handoff = _text(fact.get("first_bad_handoff")) or f"{fact.get('producer') or 'normalization'} -> {fact.get('consumer') or 'consumer'}"
            signals.append(_signal(fact, kind="PLACEHOLDER_OR_DEFAULT_SHADOWING", category="PLACEHOLDER_OR_DEFAULT_SHADOWING", handoff=handoff, repair="preserve placeholder provenance and use the consumer's existing missing-input path"))
        elif kind == "POST_REFRESH_ROW_REPLACED" or bool(fact.get("refreshed_evidence_replaced")):
            handoff = _text(fact.get("first_bad_handoff")) or "final executable refresh -> downstream execution candidate"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="preserve the accepted refreshed candidate through downstream execution consumers"))
        elif kind == "WORKER_LEASE_STALE" or _text(fact.get("lease_state")) in {"STALE_DEAD_LEASE", "LEASE_PROCESS_OWNERSHIP_CONTRADICTION"}:
            handoff = "worker shutdown -> canonical worker lease cleanup"
            signals.append(_signal(fact, kind="WORKER_LEASE_PROCESS_OWNERSHIP_CONTRADICTION", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="remove only an identity-matching released lock; recover a dead lease only after canonical ownership is disproven", severity="HIGH"))
        elif kind == "HORIZON_DEADLINE_MISSED":
            handoff = _text(fact.get("first_bad_handoff")) or "canonical horizon deadline -> natural exit evaluation"
            signals.append(_signal(fact, kind=kind, category="HORIZON_DEADLINE_MISSED", handoff=handoff, repair="ensure the existing natural exit owner evaluates the canonical deadline; do not create a parallel exit path", severity="CRITICAL"))
        elif kind == "BROKER_FILLED_CLOSURE_PENDING":
            handoff = _text(fact.get("first_bad_handoff")) or "broker-confirmed exit fill -> canonical lifecycle closure"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="reconcile the exact existing lifecycle and broker fill idempotently; do not submit another exit", severity="CRITICAL"))
        elif kind == "PRICE_TRUTH_DIVERGENCE":
            handoff = _text(fact.get("first_bad_handoff")) or "canonical current price -> downstream price consumer"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="preserve the freshest attributable price evidence through the existing consumer handoff", severity="HIGH"))
        elif kind == "BROKER_POSITION_CONTRADICTION":
            handoff = _text(fact.get("first_bad_handoff")) or "broker-reconciled position truth -> canonical position consumer"
            signals.append(_signal(fact, kind=kind, category="BROKER_POSITION_TRUTH_MISMATCH", handoff=handoff, repair="retain exact broker/canonical identity and fail closed until the existing reconciliation owner resolves the mismatch", severity="CRITICAL"))
        elif kind == "WORKER_RUNTIME_DEGRADED":
            handoff = _text(fact.get("first_bad_handoff")) or "runtime health facts -> worker ownership monitor"
            signals.append(_signal(fact, kind=kind, category="RUNTIME_RESOURCE_INTEGRITY_DEGRADED", handoff=handoff, repair="restore the existing worker/runtime owner; do not relax execution safety", severity="HIGH"))
        elif (
            (kind == "HORIZON_CONTRACT_LOSS" and fact.get("consumer_value") is not True)
            or (
                _text(fact.get("field")) == "same_session_exit_required"
                and fact.get("producer_value") is True
                and fact.get("consumer_value") is not True
            )
        ):
            handoff = _text(fact.get("first_bad_handoff")) or "canonical horizon contract -> exit-readiness consumer"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="preserve the exact canonical same-session contract through lifecycle and advisory consumers"))
        elif (
            (kind == "CANONICAL_IDENTITY_FALLBACK" and _text(fact.get("consumer_identity_status")).upper() in {"LEGACY", "UNAVAILABLE", "UNRESOLVED"})
            or (
                _text(fact.get("producer_identity_status")).upper() == "RESOLVED"
                and _text(fact.get("consumer_identity_status")).upper() in {"LEGACY", "UNAVAILABLE", "UNRESOLVED"}
            )
        ):
            handoff = _text(fact.get("first_bad_handoff")) or "canonical position identity -> advisory identity consumer"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="retain the exact current canonical lifecycle identity before applying legacy advisory overlays"))
        elif bool(fact.get("producer_value_available")) and _unavailable(fact.get("consumer_value")):
            handoff = _text(fact.get("first_bad_handoff")) or f"{fact.get('producer') or 'producer'} -> {fact.get('consumer') or 'consumer'}"
            signals.append(_signal(fact, kind="CAUSAL_HANDOFF_LOSS", category="CAUSAL_HANDOFF_LOSS", handoff=handoff, repair="preserve the existing canonical field through the verified transformation"))
        elif kind == "PRODUCER_MISSING" or ("producer_value" in fact and _unavailable(fact.get("producer_value"))):
            nondefects.append({**base, "category": "PRODUCER_EVIDENCE_MISSING", "legitimate_fail_closed": True, "reason": "producer_evidence_unavailable"})
        else:
            nondefects.append(base)
    return {
        "schema_version": VERSION,
        "facts_examined": min(len(list(facts or [])), max(1, int(limit))),
        "signals": signals,
        "nondefects": nondefects,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
    }


def causal_facts_from_candidate_traces_v1(rows: list[dict[str, Any]] | None, *, limit: int = MAX_FACTS) -> list[dict[str, Any]]:
    """Adapt current bounded candidate traces; unknown provenance stays unknown."""
    facts: list[dict[str, Any]] = []
    for row in list(rows or [])[:max(1, int(limit))]:
        if not isinstance(row, dict):
            continue
        base = {
            "current": True,
            "candidate_id": row.get("candidate_id"),
            "lifecycle_id": row.get("lifecycle_id"),
            "evidence_timestamp": row.get("timestamp_utc") or row.get("generated_at"),
            "consumer": "PaperAutopilot candidate execution",
        }
        blocker = _text(row.get("exact_blocker"))
        if blocker == "STALE_PROVIDER_NATIVE_TIMESTAMP":
            facts.append({**base, "kind": "STALE_NATIVE_QUOTE", "producer": "provider-native quote", "field": "provider_native_timestamp"})
        pretrade = dict(row.get("pretrade_contract_missing_fields_trace_v1") or {})
        forecast = _text(pretrade.get("crypto_pretrade_forecast_state"))
        if forecast == "INSUFFICIENT_FORECAST_EVIDENCE":
            facts.append({**base, "kind": "FORECAST_NOT_POSITIVE", "producer": "crypto_pretrade_forecast_v1", "field": "expected_return_range"})
        if _text(pretrade.get("risk_envelope_state")) in {"RISK_ENVELOPE_INCOMPLETE", "RISK_ENVELOPE_STALE"}:
            facts.append({**base, "kind": "RISK_EVIDENCE_MISSING", "producer": "candidate_risk_envelope_v1", "field": "candidate_risk_envelope_v1"})
        commitment = dict(row.get("entry_commitment_trace_v1") or {})
        if commitment.get("entry_edge_score_provenance") and _text((commitment.get("input_sources") or {}).get("entry_edge_score")) == "DEFAULT":
            facts.append({**base, "kind": "FIELD_LOSS", "producer": commitment.get("entry_edge_score_provenance"), "consumer": "PaperAutopilot._entry_commitment_gate_v1", "field": "entry_edge_score", "producer_value_available": True, "consumer_value": None})
        if (
            _text(commitment.get("persona_disagreement_provenance")).endswith("missing_persona_placeholder")
            and _text(commitment.get("persona_disagreement_input_state")) != "DEFAULT_UNAVAILABLE"
        ):
            facts.append({**base, "kind": "PLACEHOLDER_SHADOWING", "producer": commitment.get("persona_disagreement_provenance"), "consumer": "PaperAutopilot._entry_commitment_gate_v1", "field": "persona_disagreement_index", "placeholder_used_as_measured": True})
    return facts[:max(1, int(limit))]


def _rows(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("positions") or value.get("entries") or value.get("records") or value.get("rows") or []
    return [dict(row) for row in list(value or []) if isinstance(row, dict)]


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _timestamp(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(_text(value).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _lane(row: dict[str, Any]) -> str:
    value = _text(row.get("lane") or row.get("lane_id") or row.get("canonical_lane"))
    return value.upper() if value.upper() in LANES else ""


def _latest_timestamp(rows: Iterable[dict[str, Any]]) -> str:
    values = [
        _text(row.get("updated_at") or row.get("generated_at") or row.get("exit_fill_timestamp") or row.get("entry_fill_timestamp"))
        for row in rows
    ]
    return max((value for value in values if value), default="UNAVAILABLE")


def _dedupe(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in rows:
        key = tuple(_text(row.get(name)) for name in ("monitor", "kind", "symbol", "lane", "field", "producer", "consumer", "first_bad_handoff"))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
        if len(result) >= max(1, int(limit)):
            break
    return result


_SAME_SESSION_DEADLINE_REASONS = {
    "day_lane_overnight_breach",
    "day_lane_session_close_required",
    "scalp_lane_overnight_breach",
    "scalp_lane_session_close_required",
}
_TERMINAL_NATIVE_EXIT_STATES = {
    "BROKER_ZERO_CONFIRMED", "CLOSED", "LEARNING_ACKNOWLEDGED",
}


def _native_deadline_fact(native: dict[str, Any], position_id: Any) -> dict[str, Any] | None:
    """Use the worker-owned exit ledger when no standalone deadline is persisted."""
    lane = _lane(native)
    reason = _text(native.get("reason")).lower()
    state = _text(native.get("closure_state")).upper()
    if lane not in {"DAY", "SCALP"} or reason not in _SAME_SESSION_DEADLINE_REASONS:
        return None
    if state in _TERMINAL_NATIVE_EXIT_STATES or (
        bool(native.get("strict_truth_created")) and bool(native.get("learning_acknowledged"))
    ):
        return None
    stage = {
        "EXIT_READY": "EXIT_ORDER",
        "EXIT_BLOCKED_EXECUTION": "EXIT_ORDER",
        "SELL_SUBMITTED": "BROKER_ACK",
        "BROKER_ACKNOWLEDGED": "EXIT_FILL",
        "PARTIALLY_FILLED": "EXIT_FILL",
        "AWAITING_BROKER_ZERO": "RECONCILIATION",
        "CLOSED_PENDING_TRUTH": "STRICT_TRUTH",
        "STRICT_TRUTH_CREATED": "LEARNING_ACK",
    }.get(state, "EXIT_DECISION")
    blocker = _text(native.get("exact_blocker")) or "SAME_SESSION_DEADLINE_PASSED"
    return {
        "monitor": "LIFECYCLE_PROOF_DEADLINE",
        "current": True,
        "kind": "HORIZON_DEADLINE_MISSED",
        "symbol": native.get("symbol"),
        "lane": lane,
        "lifecycle_id": native.get("lifecycle_id") or position_id,
        "producer": "native_lane_exit_lifecycle_v1",
        "consumer": "canonical lifecycle completion",
        "field": "same_session_exit_required",
        "evidence_timestamp": native.get("last_evaluated_at") or native.get("stage_entered_at"),
        "producer_state": "DEADLINE_PASSED",
        "consumer_state": state or blocker,
        "consumer_blocker": blocker,
        "first_incomplete_stage": stage,
        "deadline_source": "native_lane_exit_lifecycle_v1.reason",
        "first_bad_handoff": "canonical same-session deadline -> existing authorized exit execution",
    }


def _price_monitor(context: dict[str, Any], *, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Compare only explicitly supplied current price facts; never select a price."""
    facts, waiting = [], []
    checked = 0
    for raw in _rows(context.get("price_truth_facts"))[:limit]:
        checked += 1
        current = bool(raw.get("current", True))
        producer_value = _number(raw.get("producer_value", raw.get("producer_price")))
        consumer_value = _number(raw.get("consumer_value", raw.get("consumer_price")))
        producer_at = _timestamp(raw.get("producer_timestamp"))
        consumer_at = _timestamp(raw.get("consumer_timestamp"))
        base = {
            "monitor": "PRICE_DATA_TRUTH", "current": current, "symbol": raw.get("symbol"), "lane": raw.get("lane"),
            "producer": raw.get("producer") or "canonical price evidence", "consumer": raw.get("consumer") or "downstream price consumer",
            "field": raw.get("field") or "current_price", "evidence_timestamp": raw.get("producer_timestamp") or raw.get("consumer_timestamp"),
        }
        if not current:
            facts.append({**base, "kind": "HISTORICAL"})
        elif producer_value is None or consumer_value is None or producer_at is None or consumer_at is None:
            waiting.append({**base, "category": "INSUFFICIENT_RUNTIME_EVIDENCE", "reason": "price_comparison_requires_attributable_values_and_timestamps", "legitimate_fail_closed": True})
        else:
            tolerance = max(0.0, float(raw.get("material_divergence_pct") or 0.01))
            divergence = abs(producer_value - consumer_value) / max(abs(producer_value), 1e-9)
            producer_newer = producer_at > consumer_at
            if producer_newer and divergence > tolerance:
                facts.append({**base, "kind": "PRICE_TRUTH_DIVERGENCE", "producer_value": producer_value, "consumer_value": consumer_value,
                              "producer_state": "FRESHER_AVAILABLE", "consumer_state": "STALE_OR_DIVERGENT", "first_bad_handoff": raw.get("first_bad_handoff") or "canonical current price -> downstream price consumer",
                              "downstream_symptom": "STALE_OR_DIVERGENT_PRICE_CONSUMED"})
    status = "DEGRADED" if any(row.get("kind") == "PRICE_TRUTH_DIVERGENCE" for row in facts) else "PASS" if checked else "INSUFFICIENT_RUNTIME_EVIDENCE"
    return {"monitor": "PRICE_DATA_TRUTH", "status": status, "facts_checked": checked, "finding_count": sum(row.get("kind") == "PRICE_TRUTH_DIVERGENCE" for row in facts), "current_state_only": True}, facts, waiting


def _lifecycle_monitor(context: dict[str, Any], *, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    traces = _rows(context.get("current_candidate_traces"))[:limit]
    truths = _rows(context.get("broker_truth_records"))[-limit:]
    lessons = _rows(context.get("canonical_lifecycle_lessons"))[-limit:]
    positions = _rows(context.get("broker_positions"))[:limit]
    # The canonical entry ledger itself retains at most 250 transitions. Scan
    # that compact source so an active lane's latest proof is not hidden by a
    # different lane's newer entries; no historical store is traversed.
    entry_records = _rows(context.get("entry_lane_horizon_integrity"))[-250:]
    native_states = dict(context.get("native_lane_exit_lifecycle") or {})
    completion = dict(context.get("multilane_completion_matrix") or {})
    matrix_lanes = dict(completion.get("lanes") or {})
    lesson_lifecycles = {_text(row.get("lifecycle_id")) for row in lessons if _text(row.get("lifecycle_id"))}
    stages = ("CANDIDATE", "ELIGIBLE_SELECTED", "ORDER_READY", "SUBMITTED", "ENTRY_FILL", "ACTIVE_MANAGEMENT", "EXIT_DECISION", "EXIT_ORDER", "EXIT_FILL", "CLOSED_LIFECYCLE", "STRICT_BROKER_TRUTH", "LEARNING_DELIVERED")
    lanes: dict[str, dict[str, Any]] = {}
    for lane in LANES:
        lane_traces = [row for row in traces if _lane(row) == lane]
        lane_truths = [row for row in truths if _lane(row) == lane]
        lane_positions = [row for row in positions if _lane(row) == lane]
        lane_entries = [row for row in entry_records if _lane(row) == lane]
        matrix = dict(matrix_lanes.get(lane) or {})
        proven: set[str] = set()
        if lane_traces or int(matrix.get("candidate_count") or 0): proven.add("CANDIDATE")
        if any(bool(row.get("eligible") or row.get("selected")) for row in lane_traces) or int(matrix.get("eligible_candidate_count") or 0): proven.add("ELIGIBLE_SELECTED")
        if any(bool(row.get("order_ready")) for row in lane_traces) or int(matrix.get("paper_order_intents") or 0): proven.add("ORDER_READY")
        if any(bool(row.get("submitted") or row.get("submission_attempted")) for row in lane_traces): proven.add("SUBMITTED")
        if lane_entries:
            proven.add("CANDIDATE")
        for entry in lane_entries:
            entry_stage = _text(entry.get("stage")).upper()
            if entry_stage in {"ORDER_READY", "SUBMITTED", "ENTRY_FILLED", "FILLED", "ACTIVE", "ACTIVE_MANAGEMENT", "ACTIVE_POSITION_AWAITING_FILL_LINK"}:
                proven.update({"CANDIDATE", "ELIGIBLE_SELECTED", "ORDER_READY"})
            if entry_stage in {"SUBMITTED", "ENTRY_FILLED", "FILLED", "ACTIVE", "ACTIVE_MANAGEMENT", "ACTIVE_POSITION_AWAITING_FILL_LINK"}:
                proven.add("SUBMITTED")
            if _text(entry.get("entry_fill_id")) or entry_stage in {"ENTRY_FILLED", "FILLED", "ACTIVE", "ACTIVE_MANAGEMENT", "ACTIVE_POSITION_AWAITING_FILL_LINK"}:
                proven.add("ENTRY_FILL")
        if lane_positions or any(_text(row.get("entry_fill_id")) for row in lane_truths):
            proven.update({"ENTRY_FILL", "ACTIVE_MANAGEMENT"})
        if any(_text(row.get("exit_reason") or row.get("exit_policy")) for row in lane_truths): proven.add("EXIT_DECISION")
        if any(_text(row.get("exit_order_id")) for row in lane_truths): proven.add("EXIT_ORDER")
        if any(_text(row.get("exit_fill_id")) for row in lane_truths): proven.update({"EXIT_FILL", "CLOSED_LIFECYCLE", "STRICT_BROKER_TRUTH"})
        if any(_text(row.get("lifecycle_id")) in lesson_lifecycles for row in lane_truths): proven.add("LEARNING_DELIVERED")
        highest = next((stage for stage in reversed(stages) if stage in proven), "NOT_PROVEN")
        first_missing = next((stage for stage in stages if stage not in proven), "NONE")
        status = "FULL_TRUTH_PROVEN" if "STRICT_BROKER_TRUTH" in proven else "PARTIALLY_PROVEN" if proven else "NOT_PROVEN"
        lanes[lane] = {"lane": lane, "highest_naturally_proven_stage": highest, "completed_natural_lifecycle_count": sum(bool(_text(row.get("exit_fill_id"))) for row in lane_truths), "strict_broker_truth_count": len(lane_truths), "latest_proof_timestamp": _latest_timestamp([*lane_traces, *lane_truths, *lane_positions, *lane_entries]), "first_missing_stage": first_missing, "current_blocker": matrix.get("first_blocker") or "UNAVAILABLE", "status": status}
    facts, waiting = [], []
    readiness = {_text(row.get("symbol")).upper(): row for row in _rows(context.get("position_exit_readiness"))}
    for position in _rows(context.get("position_lane_horizon_recovery"))[:limit]:
        if position.get("same_session_exit_required") is not True:
            continue
        deadline_raw = position.get("horizon_deadline_at") or position.get("same_session_exit_deadline_at") or position.get("exit_deadline_at")
        deadline = _timestamp(deadline_raw)
        symbol = _text(position.get("symbol")).upper()
        review = readiness.get(symbol, {})
        evaluated_at = _timestamp(review.get("evaluated_at") or review.get("generated_at"))
        base = {"monitor": "LIFECYCLE_PROOF_DEADLINE", "current": True, "symbol": symbol, "lane": _lane(position), "lifecycle_id": position.get("canonical_lifecycle_id") or position.get("canonical_position_id"), "producer": "canonical horizon recovery", "consumer": "existing natural exit readiness owner", "field": "same_session_exit_required", "evidence_timestamp": deadline_raw}
        native = _dict(native_states.get(_text(base.get("lifecycle_id"))))
        if not native:
            native_matches = [
                _dict(value) for value in native_states.values()
                if _text(value.get("symbol")).upper() == symbol
            ]
            if len(native_matches) == 1:
                native = native_matches[0]
        native_deadline = _native_deadline_fact(native, base.get("lifecycle_id"))
        if native_deadline:
            facts.append({**base, **native_deadline})
            continue
        if deadline is None:
            waiting.append({**base, "category": "INSUFFICIENT_RUNTIME_EVIDENCE", "reason": "canonical_same_session_deadline_unavailable", "legitimate_fail_closed": True})
        elif datetime.now(UTC) >= deadline and (evaluated_at is None or evaluated_at < deadline):
            facts.append({**base, "kind": "HORIZON_DEADLINE_MISSED", "producer_state": "DEADLINE_PASSED", "consumer_state": "NO_VALID_EXIT_EVALUATION", "first_bad_handoff": "canonical horizon deadline -> existing natural exit evaluation"})

    # Native exit state and its pending broker-order map are already owned by
    # the worker. Correlating the two is read-only and lets the existing
    # Sentinel distinguish a genuine broker-filled close that is still waiting
    # for local persistence from an ordinary active lifecycle.
    pending_by_position = {
        _text(item.get("position_id")): dict(item)
        for item in dict(context.get("authorized_lane_exit_pending") or {}).values()
        if isinstance(item, dict) and _text(item.get("position_id"))
    }
    for position_id, native in list(native_states.items())[:limit]:
        if not isinstance(native, dict):
            continue
        pending = pending_by_position.get(_text(position_id), {})
        status = _text(pending.get("last_order_status")).lower()
        base = {
            "monitor": "LIFECYCLE_PROOF_DEADLINE",
            "current": True,
            "symbol": native.get("symbol"),
            "lane": _lane(native),
            "lifecycle_id": native.get("lifecycle_id") or position_id,
            "producer": "authorized lane exit broker reconciliation",
            "consumer": "canonical lifecycle closure",
            "field": "exit_fill_id",
            "evidence_timestamp": pending.get("last_checked_at") or native.get("last_evaluated_at"),
        }
        native_deadline = _native_deadline_fact(native, position_id)
        if native_deadline:
            facts.append(native_deadline)
        exit_fill_id = _text(pending.get("exit_fill_id") or native.get("exit_fill_id"))
        if status in {"filled_awaiting_broker_zero", "filled_canonical_position_row_missing"} and exit_fill_id:
            facts.append({
                **base,
                "kind": "BROKER_FILLED_CLOSURE_PENDING",
                "producer_state": "BROKER_FILLED",
                "consumer_state": _text(native.get("closure_state")) or "AWAITING_BROKER_ZERO",
                "consumer_blocker": _text(native.get("exact_blocker") or pending.get("last_close_error")),
                "exit_fill_id": exit_fill_id,
                "first_bad_handoff": "broker-confirmed exit fill -> canonical lifecycle closure",
            })
        if not native_deadline and _text(native.get("deadline_requirement_status")) == "SAME_SESSION_DEADLINE_PASSED":
            facts.append({
                **base,
                "kind": "HORIZON_DEADLINE_MISSED",
                "field": "same_session_exit_required",
                "producer_state": "DEADLINE_PASSED",
                "consumer_state": _text(native.get("exact_blocker")) or "EXIT_BLOCKED_EVIDENCE",
                "first_bad_handoff": "canonical same-session deadline -> bounded executable quote evidence",
            })
    return {"monitor": "LIFECYCLE_PROOF_DEADLINE", "status": "DEGRADED" if facts else "PASS", "lanes": lanes, "deadline_checks": len(facts) + len(waiting), "observational_only": True}, facts, waiting


def _position_monitor(context: dict[str, Any], *, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    facts, waiting = [], []
    checked = 0
    for raw in _rows(context.get("broker_position_truth_facts"))[:limit]:
        checked += 1
        current = bool(raw.get("current", True))
        base = {"monitor": "BROKER_POSITION_EXECUTION_TRUTH", "current": current, "symbol": raw.get("symbol"), "lane": raw.get("lane"), "lifecycle_id": raw.get("lifecycle_id"), "producer": raw.get("producer") or "cached broker reconciliation", "consumer": raw.get("consumer") or "canonical position state", "field": raw.get("field") or "position_truth", "evidence_timestamp": raw.get("timestamp")}
        if not current:
            facts.append({**base, "kind": "HISTORICAL"})
            continue
        broker, canonical = raw.get("broker_value"), raw.get("canonical_value")
        if _unavailable(broker) or _unavailable(canonical):
            waiting.append({**base, "category": "INSUFFICIENT_RUNTIME_EVIDENCE", "reason": "broker_or_canonical_position_fact_unavailable", "legitimate_fail_closed": True})
        elif broker != canonical:
            facts.append({**base, "kind": "BROKER_POSITION_CONTRADICTION", "producer_value": broker, "consumer_value": canonical, "producer_state": "BROKER_CURRENT", "consumer_state": "CANONICAL_MISMATCH", "first_bad_handoff": raw.get("first_bad_handoff") or "cached broker reconciliation -> canonical position state"})
    for row in _rows(context.get("broker_positions"))[:limit]:
        if bool(row.get("dust") or row.get("is_dust")) and bool(row.get("meaningful_exposure") or row.get("consumes_capacity")):
            facts.append({"monitor": "BROKER_POSITION_EXECUTION_TRUTH", "current": True, "symbol": row.get("symbol"), "lane": _lane(row), "producer": "broker dust classification", "consumer": "canonical capacity/position state", "field": "dust_classification", "kind": "BROKER_POSITION_CONTRADICTION", "producer_state": "DUST", "consumer_state": "MEANINGFUL_EXPOSURE", "first_bad_handoff": "broker dust classification -> canonical capacity consumer"})
    status = "CRITICAL" if any(row.get("kind") == "BROKER_POSITION_CONTRADICTION" for row in facts) else "PASS" if checked else "INSUFFICIENT_RUNTIME_EVIDENCE"
    return {"monitor": "BROKER_POSITION_EXECUTION_TRUTH", "status": status, "facts_checked": checked, "finding_count": sum(row.get("kind") == "BROKER_POSITION_CONTRADICTION" for row in facts), "truth_arbitration_status": dict(context.get("truth_arbitration") or {}).get("status", "UNAVAILABLE")}, facts, waiting


def _resource_provider_monitor(context: dict[str, Any], *, limit: int) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    worker = dict(context.get("worker_state") or {})
    resource = dict(worker.get("resource") or {})
    provider = dict(context.get("provider_consumption_telemetry") or {})
    facts, waiting = [], []
    if worker and (worker.get("active_worker_present") is False or _text(worker.get("ownership_state")) not in {"", "SINGLE_WORKER_ACTIVE"} or _text(worker.get("last_error"))):
        facts.append({"monitor": "RESOURCE_PROVIDER_RELIABILITY", "current": True, "producer": "canonical worker state", "consumer": "runtime integrity monitor", "field": "worker_ownership", "kind": "WORKER_RUNTIME_DEGRADED", "producer_state": _text(worker.get("ownership_state")) or "WORKER_ABSENT", "consumer_state": "DEGRADED", "first_bad_handoff": "worker runtime state -> resource integrity monitor", "evidence_timestamp": worker.get("heartbeat_at")})
    attempts = successes = fresh_usable = stale = 0.0
    for row in _rows(provider.get("providers"))[:limit]:
        attempts += _number(row.get("attempted_calls") or row.get("attempts")) or 0.0
        successes += _number(row.get("successful_calls") or row.get("responses_successful") or row.get("successes")) or 0.0
        stale += _number(row.get("stale_evidence_count")) or 0.0
        fresh_usable += _number(row.get("fresh_usable_evidence_count") or row.get("fresh_usable_count")) or 0.0
        for family in _rows(row.get("endpoint_families"))[:limit]:
            successes += _number(family.get("responses_successful")) or 0.0
            stale += _number(family.get("stale_evidence_count")) or 0.0
            fresh_usable += _number(family.get("fresh_usable_evidence_count") or family.get("fresh_usable_count")) or 0.0
    stale += _number(provider.get("stale_evidence_count")) or 0.0
    if successes > 0 and stale > 0 and fresh_usable <= 0:
        waiting.append({"monitor": "RESOURCE_PROVIDER_RELIABILITY", "category": "LEGITIMATE_FAIL_CLOSED", "reason": "transport_success_without_fresh_usable_evidence", "legitimate_fail_closed": True, "transport_success_count": successes, "fresh_usable_evidence_count": fresh_usable, "stale_evidence_count": stale})
    state = "DEGRADED" if facts else "WARNING" if stale > 0 and fresh_usable <= 0 else "PASS"
    return {"monitor": "RESOURCE_PROVIDER_RELIABILITY", "status": state, "worker_heartbeat": worker.get("heartbeat_at"), "resource_state": resource.get("resource_state") or worker.get("resource_state"), "transport_success_count": successes, "fresh_usable_evidence_count": fresh_usable, "stale_evidence_count": stale, "provider_calls_added": 0}, facts, waiting


def collect_platform_integrity_monitors_v2(context: dict[str, Any] | None, *, limit: int = MAX_FACTS) -> dict[str, Any]:
    """Build four current-state advisory monitors for the canonical scanner.

    Inputs are worker-cached facts only.  The result is intentionally compact
    and contains no persistence, scheduling, provider, broker, or execution
    authority.
    """
    current = dict(context or {})
    price, price_facts, price_waiting = _price_monitor(current, limit=limit)
    lifecycle, lifecycle_facts, lifecycle_waiting = _lifecycle_monitor(current, limit=limit)
    position, position_facts, position_waiting = _position_monitor(current, limit=limit)
    resource, resource_facts, resource_waiting = _resource_provider_monitor(current, limit=limit)
    facts = _dedupe([*price_facts, *lifecycle_facts, *position_facts, *resource_facts], limit=limit)
    waiting = _dedupe([*price_waiting, *lifecycle_waiting, *position_waiting, *resource_waiting], limit=limit)
    return {"schema_version": "2.0.0", "owner": "astra_continuous_system_integrity_scanner_v1", "current_state_only": True,
            "price_data_truth": price, "lifecycle_proof_deadline": lifecycle,
            "broker_position_execution_truth": position, "resource_provider_reliability": resource,
            "facts": facts, "nondefects": waiting, "provider_calls_used": 0,
            "broker_actions_used": 0, "llm_calls_used": 0, "state_mutations": 0}


def causal_facts_from_position_horizon_handoffs_v1(
    recovery: dict[str, Any] | None,
    exit_readiness: dict[str, Any] | None,
    unified_advisory: dict[str, Any] | None,
    *,
    limit: int = MAX_FACTS,
) -> list[dict[str, Any]]:
    """Adapt current worker-owned horizon facts for the existing Sentinel path.

    The adapter is observational: it compares exact recovery identity with the
    already-built advisory projections and never reads or changes positions.
    """
    readiness_by_symbol = {
        _text(row.get("symbol")).upper(): dict(row)
        for row in list((exit_readiness or {}).get("positions") or [])
        if isinstance(row, dict) and _text(row.get("symbol"))
    }
    advisory_by_symbol = {
        _text(row.get("symbol")).upper(): dict(row)
        for row in list((unified_advisory or {}).get("positions") or [])
        if isinstance(row, dict) and _text(row.get("symbol"))
    }
    facts: list[dict[str, Any]] = []
    for recovered in list((recovery or {}).get("positions") or [])[:max(1, int(limit))]:
        if not isinstance(recovered, dict):
            continue
        symbol = _text(recovered.get("symbol")).upper()
        if not symbol:
            continue
        readiness = readiness_by_symbol.get(symbol, {})
        advisory = advisory_by_symbol.get(symbol, {})
        base = {
            "current": True,
            "lifecycle_id": recovered.get("canonical_lifecycle_id") or recovered.get("canonical_position_id"),
            "candidate_id": recovered.get("candidate_id"),
            "evidence_timestamp": (recovery or {}).get("generated_at"),
        }
        if recovered.get("same_session_exit_required") is True:
            requirement = dict(readiness.get("horizon_exit_requirement") or {})
            facts.append({
                **base,
                "kind": "HORIZON_CONTRACT_LOSS",
                "producer": "astra_position_lane_horizon_recovery_v1",
                "consumer": "astra_position_exit_readiness_v1",
                "field": "same_session_exit_required",
                "producer_value": True,
                "consumer_value": requirement.get("same_session_exit_required"),
                "first_bad_handoff": "canonical horizon recovery -> exit readiness",
            })
        if _text(recovered.get("canonical_identity_status")).upper() == "RESOLVED":
            facts.append({
                **base,
                "kind": "CANONICAL_IDENTITY_FALLBACK",
                "producer": "astra_position_lane_horizon_recovery_v1",
                "consumer": "astra_unified_position_advisory_v1",
                "field": "canonical_position_id",
                "producer_identity_status": "RESOLVED",
                "consumer_identity_status": advisory.get("canonical_identity_status"),
                "first_bad_handoff": "canonical position recovery -> unified position advisory",
            })
    return facts[:max(1, int(limit))]
