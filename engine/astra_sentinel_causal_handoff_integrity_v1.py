"""Bounded causal classification for the canonical Sentinel scanner.

This module is deliberately a pure classifier.  The worker supplies only
current, already-committed facts; it never reads providers, brokers, or raw
history and it cannot alter trading behavior.
"""
from __future__ import annotations

from typing import Any


VERSION = "1.0.0"
MAX_FACTS = 24


def _text(value: Any) -> str:
    return str(value or "").strip()


def _unavailable(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip().lower() in {"", "unknown", "unavailable", "missing", "none", "null", "n/a"})


def _signal(fact: dict[str, Any], *, kind: str, category: str, handoff: str, repair: str, severity: str = "HIGH") -> dict[str, Any]:
    return {
        "kind": kind,
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
            "worker_generation_id": fact.get("worker_generation_id"),
            "producer": fact.get("producer"),
            "consumer": fact.get("consumer"),
            "field": fact.get("field"),
            "producer_state": fact.get("producer_state") or "AVAILABLE",
            "consumer_state": fact.get("consumer_state") or "UNAVAILABLE",
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
