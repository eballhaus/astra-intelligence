"""Canonical, non-executing contracts for facts used in Astra readiness."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any


def _crypto_fact(name: str, store: str, reader: str, scope: str, prohibited: list[str]) -> dict[str, Any]:
    return {
        "fact_id": name, "human_name": name.replace("_", " ").title(),
        "canonical_owner": "PaperAutopilot canonical position store" if "LOCAL_OPEN" in name else "Alpaca paper worker authority",
        "canonical_store": store, "canonical_reader": reader, "scope_definition": scope,
        "identity_key": "position_id" if "POSITION" in name else "symbol",
        "freshness_owner": "PaperAutopilotWorker", "freshness_limit_seconds": 180,
        "fallback_allowed": False, "fallback_sources": [], "fallback_semantics": "none; fail closed",
        "diagnostic_sources": ["worker snapshots", "read-only endpoint compositions"],
        "prohibited_substitutes": prohibited, "governance_owner": "astra_continuous_governance_v1",
        "cortex_consumer": "AstraPaperProviderCortexCompletionV1", "readiness_consumers": ["crypto readiness", "crypto completion"],
        "verification_method": "canonical source and scope comparison", "failure_mode": "FAIL_CLOSED",
    }


CANONICAL_FACTS_V1: dict[str, dict[str, Any]] = {
    "LOCAL_OPEN_CRYPTO_POSITION_COUNT": _crypto_fact("LOCAL_OPEN_CRYPTO_POSITION_COUNT", "state/paper_autopilot.db.paper_positions", "read_canonical_open_crypto_positions", "OPEN + asset_type=crypto + canonical SQLite", ["PAPER_AUTOPILOT.paper_positions() broad adapter", "reconstructed lifecycle collections", "candidate ledgers", "ranking caches", "shadow rows", "diagnostic snapshots"]),
    "BROKER_OPEN_CRYPTO_POSITION_COUNT": _crypto_fact("BROKER_OPEN_CRYPTO_POSITION_COUNT", "paper_autopilot_state.last_evidence_capacity_snapshot", "evidence_accumulation_capacity_v1.crypto_open_positions", "current broker-reconciled crypto positions", ["local position adapters", "historical lifecycle rows"]),
    "CRYPTO_PENDING_ORDER_COUNT": _crypto_fact("CRYPTO_PENDING_ORDER_COUNT", "paper_autopilot_state.last_evidence_capacity_snapshot", "evidence_accumulation_capacity_v1.crypto_pending_orders", "current pending crypto broker orders", ["candidate ledgers", "historical orders"]),
    "CRYPTO_ACTIVE_COMMITMENT_COUNT": _crypto_fact("CRYPTO_ACTIVE_COMMITMENT_COUNT", "paper_autopilot_state.last_evidence_capacity_snapshot", "evidence_accumulation_capacity_v1.crypto_active_commitments", "current active crypto commitments", ["historical reservations"]),
    "CRYPTO_CAPABILITY_SUPPORTED_PAIR_COUNT": _crypto_fact("CRYPTO_CAPABILITY_SUPPORTED_PAIR_COUNT", "state/alpaca_crypto_capability_v2.json", "AlpacaPaperBroker.cached_crypto_capability", "cached paper-broker supported pair set", ["discovery universe"]),
    "CRYPTO_CAPABILITY_TRADABLE_PAIR_COUNT": _crypto_fact("CRYPTO_CAPABILITY_TRADABLE_PAIR_COUNT", "state/alpaca_crypto_capability_v2.json", "AlpacaPaperBroker.cached_crypto_capability", "cached paper-broker tradable pair set", ["ranking universe"]),
    "CRYPTO_CURRENT_QUOTE_BID": _crypto_fact("CRYPTO_CURRENT_QUOTE_BID", "paper_autopilot_state.crypto_rankings_snapshot_v1", "worker crypto quote snapshot", "current normalized crypto quote bid", ["last price", "bar low"]),
    "CRYPTO_CURRENT_QUOTE_ASK": _crypto_fact("CRYPTO_CURRENT_QUOTE_ASK", "paper_autopilot_state.crypto_rankings_snapshot_v1", "worker crypto quote snapshot", "current normalized crypto quote ask", ["last price", "bar high"]),
    "CRYPTO_CURRENT_SPREAD": _crypto_fact("CRYPTO_CURRENT_SPREAD", "paper_autopilot_state.crypto_rankings_snapshot_v1", "worker crypto quote snapshot", "current bid/ask-derived spread", ["last price", "historical bars"]),
    "CRYPTO_ELIGIBLE_COMPLETED_LIFECYCLE_COUNT": _crypto_fact("CRYPTO_ELIGIBLE_COMPLETED_LIFECYCLE_COUNT", "state/shadow_profit_loss_protection_validation_v1.json", "ShadowProfitLossProtectionValidationV1", "completed verified crypto lifecycle evidence", ["active positions", "reconstructed lifecycle rows"]),
    "BROKER_CONFIRMED_COMPLETE_TRUTH_COUNT": _crypto_fact("BROKER_CONFIRMED_COMPLETE_TRUTH_COUNT", "state/broker_truth_records_v1.json", "broker truth registry", "broker-confirmed complete truth records", ["shadow outcomes", "fixtures", "reconstructed records"]),
}


def canonical_fact_registry_v1() -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in CANONICAL_FACTS_V1.items()}


def fact_envelope_v1(fact_id: str, value: Any, *, source_timestamp: str | None = None, snapshot_id: str = "", exclusions: list[str] | None = None, confidence: float = 1.0) -> dict[str, Any]:
    contract = dict(CANONICAL_FACTS_V1.get(fact_id) or {})
    timestamp = source_timestamp or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return {"fact_id": fact_id, "value": value, "scope": contract.get("scope_definition"), "canonical": True,
            "source_owner": contract.get("canonical_owner"), "source_store": contract.get("canonical_store"),
            "source_reader": contract.get("canonical_reader"), "source_snapshot_id": snapshot_id,
            "source_timestamp": timestamp, "age_seconds": 0.0, "freshness_state": "CURRENT",
            "identity_basis": contract.get("identity_key"), "exclusions_applied": list(exclusions or []),
            "fallback_used": False, "confidence": confidence, "consumer_acknowledged": True}
