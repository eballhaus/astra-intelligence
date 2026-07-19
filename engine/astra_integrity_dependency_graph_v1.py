"""Bounded declared dependency graph for root-cause grouping."""
from __future__ import annotations

import hashlib
import json
from typing import Any


def _id(*parts: str) -> str:
    return "root-" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def dependency_graph_v1() -> dict[str, Any]:
    nodes = [
        "alpaca_crypto_latest_quote", "ProviderRouter", "data_orchestrator_quote_row",
        "crypto_ranking_snapshot", "operational_crypto_candidate", "candidate_execution_integrity",
        "crypto_readiness", "canonical_local_position_store", "broker_capacity_snapshot",
        "truth_arbitration", "continuous_governance", "cortex_truth_summary", "dashboard_summary",
        "completed_broker_lifecycle", "shadow_profit_loss_consumer",
    ]
    edges = [
        ("alpaca_crypto_latest_quote", "ProviderRouter", "produces"),
        ("ProviderRouter", "data_orchestrator_quote_row", "normalizes"),
        ("data_orchestrator_quote_row", "crypto_ranking_snapshot", "persists"),
        ("crypto_ranking_snapshot", "operational_crypto_candidate", "transforms"),
        ("operational_crypto_candidate", "candidate_execution_integrity", "gates"),
        ("candidate_execution_integrity", "crypto_readiness", "summarizes"),
        ("canonical_local_position_store", "truth_arbitration", "produces"),
        ("broker_capacity_snapshot", "truth_arbitration", "produces"),
        ("truth_arbitration", "continuous_governance", "consumes"),
        ("truth_arbitration", "cortex_truth_summary", "consumes"),
        ("continuous_governance", "dashboard_summary", "displays"),
        ("completed_broker_lifecycle", "shadow_profit_loss_consumer", "consumes"),
    ]
    return {"version": "1.0.0", "nodes": nodes, "edges": [{"from": left, "to": right, "relation": relation} for left, right, relation in edges]}


def root_cause_from_signal_v1(signal: dict[str, Any]) -> dict[str, Any]:
    """Map deterministic signals to one first bad handoff and grouped symptoms."""
    kind = str(signal.get("kind") or "UNKNOWN_SYSTEM_DEFECT")
    if kind == "QUOTE_FIELDS_DROPPED":
        category, handoff = "FIELD_DROPPED_DURING_TRANSFORMATION", "data_orchestrator quote row -> crypto ranking snapshot"
        symptoms = ["PENDING_SPREAD", "PENDING_LIQUIDITY", "CRYPTO_DATA_NOT_READY", "CRYPTO_ORDER_READY_COUNT_ZERO"]
        owner, repair = "crypto ranking transformation", "preserve canonical bid/ask/provenance through ranking snapshot"
    elif kind == "NONCANONICAL_POSITION_CLAIM":
        category, handoff = "CANONICAL_SOURCE_VIOLATION", "broad compatibility adapter -> readiness/reconciliation"
        symptoms, owner, repair = ["COUNT_MISMATCH_FAIL_CLOSED"], "crypto reconciliation consumer", "use registered canonical open-position reader"
    elif kind == "VALID_EVIDENCE_NOT_CONSUMED":
        category, handoff = "EVIDENCE_CONSUMER_FAILURE", "completed lifecycle eligibility -> shadow validation consumer"
        symptoms, owner, repair = ["SHADOW_VALIDATION_ZERO_CONSUMPTION"], "shadow profit/loss consumer", "align consumer field contract with canonical eligibility"
    elif kind == "ENDPOINT_SIDE_EFFECT":
        category, handoff = "ENDPOINT_SIDE_EFFECT", "GET handler -> mutable worker/provider/broker path"
        symptoms, owner, repair = ["GET_ROUTE_NOT_READ_ONLY"], "endpoint handler", "remove mutable call from GET composition"
    else:
        category, handoff = kind, str(signal.get("first_bad_handoff") or "unclassified critical handoff")
        symptoms, owner, repair = list(signal.get("downstream_symptoms") or []), str(signal.get("owner") or "unknown"), str(signal.get("repair") or "produce bounded human repair package")
    facts = sorted({str(item) for item in signal.get("canonical_fact_ids") or []})
    root_id = _id(category, handoff, ",".join(facts))
    return {"root_cause_id": root_id, "category": category, "severity": str(signal.get("severity") or "HIGH"),
            "first_bad_handoff": handoff, "canonical_fact_ids": facts, "affected_components": list(signal.get("affected_components") or [owner]),
            "affected_endpoints": list(signal.get("affected_endpoints") or []), "downstream_symptoms": symptoms,
            "likely_owner": owner, "smallest_safe_repair": repair,
            "safe_correction_available": bool(signal.get("safe_correction_available")),
            "human_repair_required": not bool(signal.get("safe_correction_available")),
            "verification_plan": "three consistent worker-owned scans with source-compliant consumers",
            "recurrence_state": "OPEN"}
