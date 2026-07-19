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
        "consumer_list": ["crypto readiness", "Governance", "Cortex"],
        "cortex_consumer": "AstraPaperProviderCortexCompletionV1", "readiness_consumers": ["crypto readiness", "crypto completion"],
        "verification_method": "canonical source and scope comparison", "failure_mode": "FAIL_CLOSED",
    }


def _fact(
    name: str, owner: str, store: str, reader: str, scope: str, identity: str,
    prohibited: list[str] | None = None,
) -> dict[str, Any]:
    """Register a declared authority, never infer one from a convenient cache."""
    return {
        "fact_id": name, "human_name": name.replace("_", " ").title(),
        "canonical_owner": owner, "canonical_store": store, "canonical_reader": reader,
        "scope_definition": scope, "identity_key": identity,
        "freshness_owner": "PaperAutopilotWorker", "freshness_limit_seconds": 300,
        "fallback_allowed": False, "fallback_sources": [], "fallback_semantics": "none; fail closed",
        "diagnostic_sources": ["worker snapshots", "read-only endpoint compositions"],
        "prohibited_substitutes": list(prohibited or []),
        "consumer_list": ["Governance", "Cortex", "readiness summaries"],
        "governance_owner": "astra_continuous_governance_v1",
        "cortex_consumer": "AstraPaperProviderCortexCompletionV1",
        "readiness_consumers": ["system integrity scanner"],
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
    # Runtime and account facts are worker-snapshot facts. They intentionally
    # do not authorize a live query from a diagnostic or GET route.
    "CANONICAL_WORKER_COUNT": _fact("CANONICAL_WORKER_COUNT", "PaperAutopilotWorker", "state/astra_worker_runtime_v1.json", "canonical_worker_state", "one active canonical worker", "worker_instance_id", ["tmux listings", "stale pid files"]),
    "BACKEND_LISTENER_COUNT": _fact("BACKEND_LISTENER_COUNT", "backend watchdog", "state/astra_worker_runtime_v1.json", "runtime listener snapshot", "intended backend listener count", "port", ["dashboard probe results"]),
    "FRONTEND_LISTENER_COUNT": _fact("FRONTEND_LISTENER_COUNT", "frontend watchdog", "state/astra_worker_runtime_v1.json", "runtime listener snapshot", "intended frontend listener count", "port", ["browser history"]),
    "WORKER_HEARTBEAT_AGE_SECONDS": _fact("WORKER_HEARTBEAT_AGE_SECONDS", "PaperAutopilotWorker", "state/astra_worker_runtime_v1.json", "canonical_worker_state", "latest worker heartbeat", "worker_instance_id", ["frontend timestamps"]),
    "SYSTEM_HEALTH_STATE": _fact("SYSTEM_HEALTH_STATE", "astra_runtime_governance_v1", "state/astra_worker_runtime_v1.json", "canonical_runtime_invariants", "committed runtime health", "worker_instance_id", ["HTTP response text"]),
    "PAPER_MODE_VERIFIED": _fact("PAPER_MODE_VERIFIED", "AlpacaPaperBroker", "state/paper_autopilot_state.json", "paper safety snapshot", "current paper-only verification", "broker_account", ["environment assumption"]),
    "LIVE_ENDPOINT_DETECTED": _fact("LIVE_ENDPOINT_DETECTED", "AlpacaPaperBroker", "state/paper_autopilot_state.json", "paper safety snapshot", "broker endpoint mode", "broker_account", ["dashboard configuration"]),
    "BROKER_ACCOUNT_BUYING_POWER": _fact("BROKER_ACCOUNT_BUYING_POWER", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence_accumulation_capacity_v1", "current cached paper buying power", "broker_account", ["estimated allocation"]),
    "BROKER_OPEN_POSITION_COUNT_TOTAL": _fact("BROKER_OPEN_POSITION_COUNT_TOTAL", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence_accumulation_capacity_v1", "current broker open positions", "position_id", ["lifecycle records", "candidate ledgers"]),
    "BROKER_PENDING_ORDER_COUNT_TOTAL": _fact("BROKER_PENDING_ORDER_COUNT_TOTAL", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence_accumulation_capacity_v1", "current broker pending orders", "broker_order_id", ["local candidate rows"]),
    "LOCAL_OPEN_SWING_EQUITY_POSITION_COUNT": _fact("LOCAL_OPEN_SWING_EQUITY_POSITION_COUNT", "PaperAutopilot canonical position store", "state/paper_autopilot.db", "canonical open-position reader", "OPEN + SWING_EQUITY", "position_id", ["historical positions"]),
    "BROKER_OPEN_SWING_EQUITY_POSITION_COUNT": _fact("BROKER_OPEN_SWING_EQUITY_POSITION_COUNT", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence capacity snapshot", "current SWING_EQUITY broker positions", "position_id"),
    "LOCAL_OPEN_DAY_EQUITY_POSITION_COUNT": _fact("LOCAL_OPEN_DAY_EQUITY_POSITION_COUNT", "PaperAutopilot canonical position store", "state/paper_autopilot.db", "canonical open-position reader", "OPEN + DAY_EQUITY", "position_id", ["historical positions"]),
    "BROKER_OPEN_DAY_EQUITY_POSITION_COUNT": _fact("BROKER_OPEN_DAY_EQUITY_POSITION_COUNT", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence capacity snapshot", "current DAY_EQUITY broker positions", "position_id"),
    "LOCAL_OPEN_ETF_POSITION_COUNT": _fact("LOCAL_OPEN_ETF_POSITION_COUNT", "PaperAutopilot canonical position store", "state/paper_autopilot.db", "canonical open-position reader", "OPEN + ETF", "position_id", ["ranking rows"]),
    "BROKER_OPEN_ETF_POSITION_COUNT": _fact("BROKER_OPEN_ETF_POSITION_COUNT", "Alpaca paper worker authority", "state/paper_autopilot_state.json", "evidence capacity snapshot", "current ETF broker positions", "position_id"),
    "CURRENT_CANDIDATE_COUNT_BY_LANE": _fact("CURRENT_CANDIDATE_COUNT_BY_LANE", "PaperAutopilotWorker", "state/paper_autopilot_state.json", "worker candidate snapshot", "current cached candidates by lane", "candidate_id", ["historical candidate ledger"]),
    "FRESH_CANDIDATE_COUNT_BY_LANE": _fact("FRESH_CANDIDATE_COUNT_BY_LANE", "PaperAutopilotWorker", "state/paper_autopilot_state.json", "worker candidate snapshot", "fresh cached candidates by lane", "candidate_id", ["historical candidate ledger"]),
    "ORDER_READY_COUNT_BY_LANE": _fact("ORDER_READY_COUNT_BY_LANE", "candidate_execution_integrity_v1", "state/paper_autopilot_state.json", "execution integrity snapshot", "current order-ready candidates by lane", "candidate_id", ["ranking scores"]),
    "CURRENT_QUOTE_BID": _fact("CURRENT_QUOTE_BID", "ProviderRouter", "state/paper_autopilot_state.json", "worker quote snapshot", "current normalized bid", "symbol", ["last price", "bar low"]),
    "CURRENT_QUOTE_ASK": _fact("CURRENT_QUOTE_ASK", "ProviderRouter", "state/paper_autopilot_state.json", "worker quote snapshot", "current normalized ask", "symbol", ["last price", "bar high"]),
    "CURRENT_QUOTE_SPREAD": _fact("CURRENT_QUOTE_SPREAD", "ProviderRouter", "state/paper_autopilot_state.json", "worker quote snapshot", "current bid/ask derived spread", "symbol", ["zero default", "historical bar range"]),
    "CURRENT_QUOTE_TIMESTAMP": _fact("CURRENT_QUOTE_TIMESTAMP", "ProviderRouter", "state/paper_autopilot_state.json", "worker quote snapshot", "current quote source timestamp", "symbol", ["ranking timestamp"]),
    "CURRENT_COMPLETED_BAR_VOLUME": _fact("CURRENT_COMPLETED_BAR_VOLUME", "data_orchestrator", "state/paper_autopilot_state.json", "canonical completed bar", "completed-bar volume", "symbol", ["fabricated zero"]),
    "BROKER_CONFIRMED_ENTRY_COUNT": _fact("BROKER_CONFIRMED_ENTRY_COUNT", "broker truth registry", "state/broker_truth_records_v1.json", "broker truth registry", "verified broker entries", "entry_fill_id", ["provisional entries"]),
    "BROKER_CONFIRMED_EXIT_COUNT": _fact("BROKER_CONFIRMED_EXIT_COUNT", "broker truth registry", "state/broker_truth_records_v1.json", "broker truth registry", "verified broker exits", "exit_fill_id", ["shadow exits"]),
    "COMPLETE_BROKER_TRUTH_COUNT": _fact("COMPLETE_BROKER_TRUTH_COUNT", "broker truth registry", "state/broker_truth_records_v1.json", "broker truth registry", "complete broker-confirmed lifecycles", "lifecycle_id", ["reconstructed lifecycles"]),
    "OFFICIAL_METRIC_ELIGIBLE_COUNT": _fact("OFFICIAL_METRIC_ELIGIBLE_COUNT", "official metrics consumer", "state/broker_truth_records_v1.json", "official metric eligibility", "verified official metric records", "lifecycle_id", ["shadow records"]),
    "LIFECYCLE_LEARNING_ELIGIBLE_COUNT": _fact("LIFECYCLE_LEARNING_ELIGIBLE_COUNT", "lifecycle learning consumer", "state/broker_truth_records_v1.json", "lifecycle learning eligibility", "verified lifecycle learning records", "lifecycle_id", ["legacy unlinked records"]),
    "SHADOW_VALIDATION_ELIGIBLE_COUNT": _fact("SHADOW_VALIDATION_ELIGIBLE_COUNT", "ShadowProfitLossProtectionValidationV1", "state/shadow_profit_loss_protection_validation_v1.json", "shadow validation eligibility", "validated lifecycle shadow input", "lifecycle_id", ["invalid lifecycles"]),
    "ACTIVE_CRITICAL_CONTRADICTION_COUNT": _fact("ACTIVE_CRITICAL_CONTRADICTION_COUNT", "TruthContradictionRegistryV1", "state/astra_governance_contradictions_v1.json", "contradiction registry", "active critical contradictions", "contradiction_id"),
    "ACTIVE_HIGH_CONTRADICTION_COUNT": _fact("ACTIVE_HIGH_CONTRADICTION_COUNT", "TruthContradictionRegistryV1", "state/astra_governance_contradictions_v1.json", "contradiction registry", "active high contradictions", "contradiction_id"),
    "RECURRENT_CONTRADICTION_COUNT": _fact("RECURRENT_CONTRADICTION_COUNT", "TruthContradictionRegistryV1", "state/astra_governance_contradictions_v1.json", "contradiction registry", "recurrent contradictions", "contradiction_id"),
    "SAFE_CORRECTION_APPLIED_COUNT": _fact("SAFE_CORRECTION_APPLIED_COUNT", "safe correction registry", "state/astra_safe_correction_transactions_v1.json", "safe correction registry", "verified nonbehavioral corrections", "correction_id"),
    "HUMAN_REPAIR_REQUIRED_COUNT": _fact("HUMAN_REPAIR_REQUIRED_COUNT", "system integrity scanner", "state/astra_integrity_root_causes_v1.json", "root cause registry", "active human repair packages", "root_cause_id"),
    "CORTEX_REJECTED_CLAIM_COUNT": _fact("CORTEX_REJECTED_CLAIM_COUNT", "AstraPaperProviderCortexCompletionV1", "state/paper_autopilot_state.json", "truth arbitration summary", "claims Cortex rejected", "contradiction_id"),
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
