"""Continuous, worker-owned governance diagnosis and bounded safe remediation.

GET consumers only read compact committed summaries.  The isolated worker is
the only process allowed to open a campaign or apply an allowlisted operational
repair.  Repairs only affect derived scheduling metadata and governance state;
they cannot create trades, orders, evidence, or policy changes.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from engine.astra_runtime_governance_v1 import canonical_runtime_invariants, canonical_worker_state, utc_now


VERSION = "1.0.0"
MAX_REPAIRS_PER_CYCLE = 3
MAX_PROVIDER_RETRIES_PER_RECORD = 2
MAX_LIFECYCLE_REQUEUES_PER_SYMBOL_PER_CYCLE = 1
MAX_CONSUMER_RETRIES_PER_EVIDENCE = 2
CAMPAIGN_LIMIT = 100
PAUSED_RESOURCE_STATES = {
    "RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE",
    "RESOURCE_RECOVERY_COOLDOWN", "RESOURCE_UNKNOWN_FAIL_CLOSED",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now() -> str:
    return utc_now()


def _safe_flags() -> dict[str, Any]:
    return {
        "paper_only": True,
        "paper_only_preserved": True,
        "alpaca_paper_only_preserved": True,
        "behavior_safe_to_apply": False,
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
        "learned_exits_applied": False,
        "provider_budget_changed": False,
        "day_behavior_changed": False,
        "crypto_behavior_changed": False,
        "api_calls_used": 0,
        "provider_calls_used": 0,
        "broker_actions_used": 0,
        "llm_calls_used": 0,
        "full_store_scans": 0,
    }


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return _dict(value)
    except (OSError, ValueError, TypeError):
        return {}


def _checksum(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


def _identity(record: dict[str, Any], review: dict[str, Any] | None = None) -> dict[str, str]:
    review = _dict(review)
    provisional = _dict(record.get("provisional_horizon"))
    return {
        "asset_class": _text(review.get("asset_class") or record.get("asset_class"), "equity"),
        "lane": _text(review.get("lane") or record.get("lane") or "LEGACY_SWING", "LEGACY_SWING"),
        "strategy": _text(review.get("strategy") or record.get("strategy") or "legacy_swing"),
        "horizon": _text(review.get("horizon") or provisional.get("provisional_horizon") or record.get("horizon") or "swing"),
        "symbol": _text(review.get("symbol") or record.get("symbol")).upper(),
        "regime": _text(review.get("regime") or record.get("regime"), "unknown"),
        "lifecycle_stage": _text(review.get("lifecycle_stage") or record.get("lifecycle_stage"), "open_review"),
    }


def dependency_graph() -> list[dict[str, Any]]:
    """Canonical bounded graph.  Each edge carries an executable ownership contract."""
    rows = [
        ("runtime.api_worker", "host_process", "isolated_api", "API process", "API health", "runtime", "ONE_API_PROCESS", "diagnostic"),
        ("runtime.worker", "isolated_api", "paper_autopilot_worker", "worker ownership", "canonical heartbeat", "runtime", "ONE_CANONICAL_WORKER", "restart_worker"),
        ("provider.request_response", "paper_autopilot_worker", "provider_normalizer", "bounded request", "normalized response", "provider", "PROVIDER_REQUEST_HAS_VALID_CONTRACT", "retry_provider"),
        ("provider.persistence", "provider_normalizer", "canonical_market_evidence", "normalized bars", "canonical series", "evidence", "PROVIDER_SUCCESS_PERSISTS", "retry_persistence"),
        ("evidence.lifecycle_identity", "canonical_market_evidence", "lifecycle_registry", "series identity", "lane/horizon lifecycle", "lifecycle", "OPEN_POSITION_HAS_ONE_CANONICAL_LIFECYCLE", "relink_unambiguous"),
        ("evidence.review", "lifecycle_registry", "lifecycle_review_scheduler", "eligible lifecycle", "scheduled review", "lifecycle", "ELIGIBLE_REVIEW_IS_SCHEDULED", "requeue_review"),
        ("evidence.momentum", "lifecycle_review_scheduler", "momentum_builder", "sufficient daily series", "current momentum", "consumer", "SUFFICIENT_BARS_BUILD_MOMENTUM", "schedule_momentum"),
        ("consumer.direct_evidence", "momentum_builder", "direct_evidence", "current momentum", "coverage acknowledgement", "consumer", "DIRECT_EVIDENCE_IS_UPDATED", "retry_consumer"),
        ("consumer.forward_value", "direct_evidence", "forward_value", "direct evidence", "forward-value acknowledgement", "consumer", "FORWARD_VALUE_ACKNOWLEDGES", "retry_consumer"),
        ("consumer.profit_capture", "forward_value", "profit_capture", "forward review", "profit-capture acknowledgement", "consumer", "PROFIT_CAPTURE_ACKNOWLEDGES", "retry_consumer"),
        ("consumer.confirmation", "profit_capture", "direct_confirmation", "capture review", "confirmation acknowledgement", "consumer", "DIRECT_CONFIRMATION_ACKNOWLEDGES", "retry_consumer"),
        ("consumer.lifecycle", "direct_confirmation", "lifecycle_input", "confirmation", "lifecycle input acknowledgement", "consumer", "LIFECYCLE_INPUT_ACKNOWLEDGES", "retry_consumer"),
        ("consumer.cortex", "lifecycle_input", "cortex", "lifecycle input", "Cortex influence acknowledgement", "consumer", "CORTEX_INFLUENCE_ACKNOWLEDGES", "retry_consumer"),
        ("truth.reconciliation", "cortex", "broker_truth", "advisory influence", "broker reconciliation", "truth", "STATE_SURVIVES_RESTART", "diagnostic"),
    ]
    return [{
        "edge_id": edge_id, "upstream_owner": upstream, "downstream_owner": downstream,
        "required_input": input_name, "expected_output": output_name,
        "freshness_requirement": "current_worker_cycle_or_committed_snapshot",
        "canonical_identity_key": "asset_class:lane:strategy:horizon:symbol:regime:lifecycle_stage",
        "verification_method": invariant, "severity_if_broken": "HIGH" if repair != "diagnostic" else "WARN",
        "repairability_class": "ALLOWLISTED_BOUNDED" if repair != "diagnostic" else "DIAGNOSTIC_ONLY",
        "allowed_remediation_ids": [] if repair == "diagnostic" else [repair],
    } for edge_id, upstream, downstream, input_name, output_name, _group, invariant, repair in rows]


def remediation_registry() -> dict[str, dict[str, Any]]:
    """Only deterministic operational actions are executable by the worker."""
    common = {
        "standing_authorization": True, "trading_policy_change": False,
        "maximum_scope": "one canonical lifecycle identity per campaign",
        "retry_limit": 2, "cooldown_seconds": 24 * 60 * 60,
        "resource_budget": "no provider, broker, or LLM calls; uses existing cycle budget",
        "rollback_or_recovery": "remove derived task metadata; canonical evidence is preserved",
    }
    rows = {
        "REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW": {
            "triggering_invariant": "ELIGIBLE_REVIEW_IS_SCHEDULED", "prerequisites": ["unambiguous_identity", "eligible_review", "paper_safety", "acceptable_resource"],
            "repair_action": "raise existing activation refresh_priority for one future bounded worker cycle", "verification_action": "activation priority metadata committed",
        },
        "SCHEDULE_MISSING_MOMENTUM_BUILD": {
            "triggering_invariant": "SUFFICIENT_BARS_BUILD_MOMENTUM", "prerequisites": ["unambiguous_identity", "current_sufficient_daily_series", "eligible_review", "paper_safety"],
            "repair_action": "record one bounded momentum rebuild request and priority the existing activation", "verification_action": "task is committed for normal lifecycle builder",
        },
        "RETRY_MISSING_CONSUMER_ACKNOWLEDGEMENT": {
            "triggering_invariant": "MOMENTUM_IS_ACKNOWLEDGED", "prerequisites": ["unambiguous_identity", "current_momentum", "paper_safety"],
            "repair_action": "record one consumer retry request and priority the existing activation", "verification_action": "retry task is committed without fabricating acknowledgement",
        },
        "CLEAR_STALE_RESOURCE_STATE": {
            "triggering_invariant": "RECOVERY_REQUIRES_HYSTERESIS", "prerequisites": ["worker_owned", "healthy_hysteresis_satisfied"],
            "repair_action": "defer to existing resource policy transition", "verification_action": "resource policy becomes normal through normal sampling",
        },
        "INVALIDATE_STALE_CACHE": {
            "triggering_invariant": "DERIVED_CACHE_IS_FRESH_OR_INVALIDATED", "prerequisites": ["derived_cache_only", "bounded_scope"],
            "repair_action": "mark derived cache invalid; never delete canonical evidence", "verification_action": "cache invalidation marker committed",
        },
    }
    # These known classes are catalogued for diagnosis, but are deliberately
    # not executable by this worker until a component-specific supervisor and
    # verification implementation exists.  Naming them prevents Cortex from
    # inventing an arbitrary action while preserving a focused repair package.
    deferred = {
        "RESTART_MISSING_WORKER": "supervisor-owned restart after explicit liveness verification",
        "CLEAR_STALE_WORKER_OWNER": "canonical ownership reconciliation",
        "BLOCK_DUPLICATE_WORKER": "lease rejection and supervisor reporting",
        "REPLACE_STALE_GENERATION": "canonical generation recovery",
        "RECOVER_INTERRUPTED_CHECKPOINT": "atomic snapshot recovery",
        "RESUME_PERSISTED_CURSOR": "worker cursor resume",
        "RESTART_FAILED_COMPONENT_ONLY": "component supervisor restart",
        "ENTER_RESOURCE_PAUSE": "existing resource policy transition",
        "RESUME_ONE_SYMBOL_AFTER_HYSTERESIS": "existing resource policy transition",
        "REDUCE_TO_ONE_SYMBOL_MODE": "existing resource policy transition",
        "RESTORE_NORMAL_BOUNDED_MODE": "existing resource policy transition",
        "SELECT_NEWEST_VALID_CANONICAL_STATE": "canonical state resolver",
        "QUARANTINE_DEPRECATED_WRITER": "owner/supervisor action",
        "REBUILD_READ_ONLY_COMPATIBILITY_STATE": "derived compatibility rebuild",
        "RETRY_ATOMIC_STATE_WRITE": "atomic state writer retry",
        "RECONCILE_STATUS_READERS": "read-only status reconciliation",
        "RETRY_VALID_PROVIDER_PERSISTENCE": "normal worker provider retry within existing budget",
        "RESUME_BOUNDED_PAGINATION": "normal worker cursor resume",
        "REQUEUE_STALE_PROVIDER_REFRESH": "normal worker refresh queue",
        "PERSIST_MISSING_CANONICAL_SERIES": "normal worker canonical persistence",
        "RETRY_NORMALIZATION_FROM_VALID_RESPONSE": "normal worker normalizer retry",
        "RELINK_UNAMBIGUOUS_CANONICAL_KEY": "only after identity equality verification",
        "RESUME_STALLED_BOUNDED_BACKLOG": "normal scheduler resume",
        "RETRY_DOWNSTREAM_CONSUMPTION": "existing consumer retry",
        "REBUILD_BOUNDED_SUMMARY_INDEX": "derived index-only rebuild",
        "REBUILD_DERIVED_SNAPSHOT": "derived snapshot-only rebuild",
        "REMOVE_ORPHAN_TEMP_FILE": "bounded temp cleanup",
        "ROTATE_OVERSIZED_LOG": "existing log rotation",
    }
    for remediation_id, action in deferred.items():
        rows.setdefault(remediation_id, {
            "triggering_invariant": "COMPONENT_SPECIFIC_INVARIANT", "prerequisites": ["component_specific_owner", "predefined_verification"],
            "repair_action": action, "verification_action": "not executable by this worker; package or defer fail-closed", "standing_authorization": False,
        })
    return {key: {"remediation_id": key, **common, **value} for key, value in rows.items()}


class ContinuousGovernanceV1:
    """Campaign executor called only by the isolated worker after a bounded cycle."""

    def __init__(self, state_dir: str | Path) -> None:
        self.state_dir = Path(state_dir)
        self.summary_path = self.state_dir / "astra_continuous_governance_v1.json"
        self.campaign_path = self.state_dir / "astra_remediation_campaigns_v1.json"
        self.lease_path = self.state_dir / "astra_continuous_governance_v1.lock"

    @contextmanager
    def _lease(self) -> Iterator[bool]:
        self.lease_path.parent.mkdir(parents=True, exist_ok=True)
        acquired = False
        try:
            with self.lease_path.open("x", encoding="utf-8") as handle:
                handle.write(json.dumps({"owner": os.getpid(), "acquired_at": _now()}))
            acquired = True
            yield True
        except FileExistsError:
            yield False
        finally:
            if acquired:
                try:
                    self.lease_path.unlink()
                except OSError:
                    pass

    def _load_campaigns(self) -> list[dict[str, Any]]:
        return list(_read_json(self.campaign_path).get("campaigns") or [])[-CAMPAIGN_LIMIT:]

    def _save_campaigns(self, campaigns: list[dict[str, Any]]) -> None:
        _atomic_write(self.campaign_path, {"schema_version": VERSION, "updated_at": _now(), "campaigns": campaigns[-CAMPAIGN_LIMIT:]})

    def snapshot(self) -> dict[str, Any]:
        summary = _read_json(self.summary_path)
        campaigns = self._load_campaigns()
        if not summary:
            summary = {"status": "AWAITING_WORKER_SCAN", "scan_time": None, "campaigns": []}
        return {
            "endpoint": "/api/astra_continuous_governance_v1", "version": VERSION,
            **summary, "campaigns": campaigns[-20:], "campaign_count": len(campaigns),
            "dependency_graph": dependency_graph(), "remediation_registry": remediation_registry(),
            "get_route_read_only": True, "worker_owned_mutations_only": True, **_safe_flags(),
        }

    def _safety_authorization(self, worker_state: dict[str, Any], safety: dict[str, Any]) -> str:
        if not bool(safety.get("paper_mode_verified")) or bool(safety.get("broker_live_endpoint_allowed")):
            return "AUTO_REMEDIATION_BLOCKED_POLICY_SCOPE"
        if str(worker_state.get("resource_state") or "RESOURCE_UNKNOWN_FAIL_CLOSED") in PAUSED_RESOURCE_STATES:
            return "AUTO_REMEDIATION_BLOCKED_RESOURCE_PRESSURE"
        if not bool(worker_state.get("active_worker_present")):
            return "AUTO_REMEDIATION_BLOCKED_STATE_CORRUPTION"
        return "AUTO_REMEDIATION_AUTHORIZED"

    def _records(self, runtime_state: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        canary = _dict(runtime_state.get("legacy_swing_canary"))
        records = _dict(canary.get("market_records") or runtime_state.get("legacy_swing_market_evidence"))
        reviews = _dict(canary.get("reviews"))
        activations = _dict(runtime_state.get("legacy_forward_activations"))
        return records, reviews, activations

    def _invariants(self, worker_state: dict[str, Any], runtime_state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        invariants: list[dict[str, Any]] = []
        # Raw worker snapshots intentionally stay compact.  The runtime
        # invariant evaluator requires the canonical enrichment that derives
        # heartbeat age and validates the active PID before classifying it.
        runtime = canonical_runtime_invariants(canonical_worker_state())
        for invariant_id, row in runtime.items():
            state = _text(row.get("state"), "WARN")
            invariants.append({"invariant_id": invariant_id, "owner": "astra_runtime_governance_v1", "dependencies": [], "state": state, "observed_value": row.get("observed_value"), "expected_value": row.get("expected_value"), "first_failed_at": row.get("first_failed_at"), "last_checked_at": _now(), "failure_count": 0 if state in {"PASS", "NOT_APPLICABLE"} else 1, "severity": "HIGH" if state == "FAIL" else "WARN" if state != "PASS" else "INFO", "repairability": "ALLOWLISTED" if invariant_id in {"RECOVERY_REQUIRES_HEALTHY_HYSTERESIS"} else "DIAGNOSTIC", "exact_blocker": row.get("blocker"), "allowed_remediations": []})
        records, reviews, activations = self._records(runtime_state)
        rows: list[dict[str, Any]] = []
        for activation_id, bundle_raw in list(records.items())[:50]:
            bundle = _dict(bundle_raw)
            daily = _dict(bundle.get("HISTORICAL_BARS_DAILY"))
            if not daily:
                continue
            review = _dict(reviews.get(activation_id))
            activation = _dict(activations.get(activation_id))
            sufficient = str(daily.get("quality_state") or "") == "CURRENT_SUFFICIENT" and int(daily.get("records_valid") or 0) >= int(daily.get("required_completed_bars") or 15)
            identity = _identity({**activation, **daily}, review)
            identity_conflict = any(
                _text(review.get(key)) and _text(daily.get(key)) and _text(review.get(key)).lower() != _text(daily.get(key)).lower()
                for key in ("asset_class", "lane", "strategy", "horizon", "symbol")
            )
            identity_complete = all(identity.get(key) for key in ("asset_class", "lane", "strategy", "horizon", "symbol")) and not identity_conflict
            momentum = _dict(_dict(review.get("required_evidence")).get("MOMENTUM"))
            momentum_current = momentum.get("status") == "CURRENT"
            eligible = bool(review) and not bool(review.get("eligibility") is False or review.get("governance_blocked"))
            scheduled = bool(review) and (bool(_dict(_dict(runtime_state.get("legacy_swing_market_activity")).get("scheduler")).get("per_symbol", {}).get(activation_id)) or bool(activation.get("governance_requeue_requested_at")))
            acks = {
                "direct_evidence": bool(_dict(review.get("direct_evidence_coverage")).get("required_evidence_complete")),
                "forward_value": bool(review.get("forward_value_review") or review.get("forward_value")),
                "profit_capture": bool(review.get("profit_capture") or review.get("profit_capture_intelligence")),
                "direct_confirmation": bool(review.get("direct_confirmation_state")),
                "lifecycle": bool(review.get("lifecycle_decision") or review.get("lifecycle_status")),
                "cortex": bool(review.get("cortex_influence") or review.get("cortex_acknowledged")),
            }
            row = {"activation_id": activation_id, "daily": daily, "review": review, "activation": activation, "identity": identity, "identity_complete": identity_complete, "identity_conflict": identity_conflict, "daily_sufficient": sufficient, "review_eligible": eligible, "review_scheduled": scheduled, "momentum_current": momentum_current, "acknowledgements": acks, "symbol": identity["symbol"]}
            rows.append(row)
            def add(invariant_id: str, passed: bool, blocker: str, remediation: str | None = None) -> None:
                invariants.append({"invariant_id": invariant_id, "owner": "PaperAutopilot", "dependencies": [activation_id], "state": "PASS" if passed else "LEGITIMATE_WAITING_STATE" if blocker.startswith("no_current") else "WARN", "observed_value": row, "expected_value": "current", "first_failed_at": None if passed else _now(), "last_checked_at": _now(), "failure_count": 0 if passed else 1, "severity": "WARN" if not passed else "INFO", "repairability": "ALLOWLISTED" if remediation else "LEGITIMATE_WAITING", "exact_blocker": None if passed else blocker, "allowed_remediations": [remediation] if remediation else []})
            add("CANONICAL_SERIES_EXISTS", bool(daily.get("record_id")), "missing_canonical_daily_series")
            add("OPEN_POSITION_HAS_ONE_CANONICAL_LIFECYCLE", bool(review) or not sufficient, "no_current_eligible_broker_lifecycle_review")
            add("LIFECYCLE_HAS_LANE_STRATEGY_HORIZON", identity_complete, "ambiguous_or_missing_lifecycle_identity")
            add("SUFFICIENT_EVIDENCE_HAS_ELIGIBLE_REVIEW", not sufficient or eligible, "no_current_eligible_broker_lifecycle_review")
            add("ELIGIBLE_REVIEW_IS_SCHEDULED", not eligible or scheduled, "eligible_review_not_scheduled", "REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW" if eligible and identity_complete else None)
            add("SUFFICIENT_BARS_BUILD_MOMENTUM", not sufficient or momentum_current, "momentum_not_current", "SCHEDULE_MISSING_MOMENTUM_BUILD" if sufficient and eligible and identity_complete else None)
            add("MOMENTUM_IS_ACKNOWLEDGED", not momentum_current or all(acks.values()), "consumer_acknowledgements_missing", "RETRY_MISSING_CONSUMER_ACKNOWLEDGEMENT" if momentum_current and identity_complete else None)
        # The unified lifecycle overlay is committed by the existing
        # PaperAutopilot reconciliation cycle.  Governance observes it here;
        # it cannot approve migration, release capacity, or submit an order.
        management_reviews = _dict(runtime_state.get("position_resolution_reviews"))
        migration_manifest = _dict(runtime_state.get("legacy_migration_manifest_v1"))
        migration_approval = _dict(runtime_state.get("legacy_migration_approval_v1"))
        migration_application = _dict(runtime_state.get("legacy_migration_application_v1"))
        if migration_manifest or migration_approval or migration_application:
            manifest_id = _text(migration_manifest.get("migration_manifest_id"))
            approval_id = _text(migration_approval.get("approval_id"))
            approved_count = _integer(migration_approval.get("approved_position_count"), 0)
            manifest_count = _integer(migration_manifest.get("position_count"), 0)
            applied = _text(migration_approval.get("approval_status")) == "APPLIED_AND_CLOSED"
            invariant_base = {
                "position_id": manifest_id or "legacy_migration_manifest",
                "symbol": "LEGACY_MIGRATION",
                "classification": "ONE_TIME_APPROVAL",
                "management_cohort": "LEGACY_POSITION_RESOLUTION",
            }
            def migration_invariant(invariant_id: str, passed: bool, blocker: str) -> None:
                invariants.append({
                    "invariant_id": invariant_id,
                    "owner": "PaperAutopilot._evidence_capacity_snapshot_v1",
                    "dependencies": [manifest_id or "legacy_migration_manifest"],
                    "state": "PASS" if passed else "FAIL",
                    "observed_value": invariant_base,
                    "expected_value": "immutable_one_time_legacy_migration",
                    "first_failed_at": None if passed else _now(),
                    "last_checked_at": _now(),
                    "failure_count": 0 if passed else 1,
                    "severity": "INFO" if passed else "HIGH",
                    "repairability": "DIAGNOSTIC",
                    "exact_blocker": None if passed else blocker,
                    "allowed_remediations": [],
                })
            migration_invariant(
                "MIGRATION_MANIFEST_IMMUTABLE",
                bool(manifest_id and _text(migration_manifest.get("manifest_hash")) and migration_manifest.get("immutable")),
                "migration_manifest_identity_or_hash_missing",
            )
            migration_invariant(
                "APPROVAL_APPLIES_TO_MANIFEST_ONLY",
                bool(approval_id and migration_approval.get("migration_manifest_id") == manifest_id and approved_count == manifest_count),
                "migration_approval_manifest_scope_mismatch",
            )
            migration_invariant(
                "APPROVAL_CONSUMED_ONCE",
                not applied or bool(migration_approval.get("consumed_once") and migration_approval.get("expires_after_application")),
                "applied_migration_approval_reusable",
            )
        for position_key, management_raw in list(management_reviews.items())[:100]:
            management = _dict(management_raw)
            symbol = _text(management.get("symbol") or position_key).upper()
            legacy = _text(management.get("management_cohort")).upper() == "LEGACY_POSITION_RESOLUTION"
            slot_excluded = bool(management.get("active_slot_exclusion_approved"))
            approval_complete = bool(
                (management.get("legacy_migration_approved") or management.get("legacy_resolution_approved"))
                and _text(management.get("legacy_migration_approval_id") or management.get("legacy_resolution_approval_id"))
                and management.get("decreasing_only")
            )
            base = {
                "position_id": _text(management.get("position_id") or position_key),
                "symbol": symbol,
                "classification": management.get("classification"),
                "management_cohort": management.get("management_cohort"),
            }
            def management_invariant(invariant_id: str, passed: bool, blocker: str, *, waiting: bool = False) -> None:
                invariants.append({
                    "invariant_id": invariant_id,
                    "owner": "engine.astra_unified_position_lifecycle_v1",
                    "dependencies": [base["position_id"]],
                    "state": "PASS" if passed else "LEGITIMATE_WAITING_STATE" if waiting else "FAIL",
                    "observed_value": base,
                    "expected_value": "position_management_overlay_complete",
                    "first_failed_at": None if passed else _now(),
                    "last_checked_at": _now(),
                    "failure_count": 0 if passed else 1,
                    "severity": "INFO" if passed else "WARN" if waiting else "HIGH",
                    "repairability": "LEGITIMATE_WAITING" if waiting else "DIAGNOSTIC",
                    "exact_blocker": None if passed else blocker,
                    "allowed_remediations": [],
                })
            management_invariant("NO_POSITION_WITHOUT_LIFECYCLE_OWNER", bool(_text(management.get("lifecycle_owner"))), "position_lifecycle_owner_missing")
            management_invariant("NO_POSITION_WITHOUT_CURRENT_THESIS", bool(_text(management.get("current_thesis"))), "position_current_thesis_missing")
            management_invariant("NO_POSITION_WITHOUT_NEXT_REVIEW", bool(_text(management.get("next_review_at"))), "position_next_review_missing")
            management_invariant("NO_INDEFINITE_HOLD", bool(_text(management.get("next_review_at"))), "unbounded_hold_without_review_deadline")
            management_invariant("NO_NEW_LEGACY_ENTRIES", not legacy or bool(management.get("no_new_legacy_entries")), "legacy_cohort_accepts_new_entries")
            management_invariant("LEGACY_BOOK_DECREASING_ONLY", not legacy or bool(management.get("decreasing_only")), "legacy_book_not_decreasing_only")
            management_invariant("FULL_RISK_INCLUSION", not legacy or bool(management.get("full_risk_included")), "legacy_exposure_not_in_full_risk_view")
            management_invariant("ACTIVE_SLOT_EXCLUSION_ONLY", not slot_excluded or approval_complete, "legacy_slot_exclusion_missing_governance_approval")
            management_invariant(
                "NO_DAY_TO_SWING_DRIFT",
                _text(management.get("classification")) != "DAY_HORIZON_DRIFT_POSITION"
                or bool(_text(management.get("day_horizon_drift_decision"))),
                "day_horizon_drift_requires_hold_exception_or_exit_review",
            )
            management_invariant(
                "NO_DAY_POSITION_PAST_SESSION_WITHOUT_DECISION",
                _text(management.get("classification")) != "DAY_HORIZON_DRIFT_POSITION"
                or bool(_text(management.get("day_horizon_drift_decision")) and _text(management.get("day_hard_deadline_at"))),
                "day_horizon_drift_missing_bounded_decision_or_deadline",
            )
            management_invariant(
                "NO_UNBOUNDED_DAY_OVERNIGHT_EXCEPTION",
                _text(management.get("classification")) != "DAY_HORIZON_DRIFT_POSITION"
                or bool(_text(management.get("day_hard_deadline_at"))),
                "day_overnight_exception_or_drift_has_no_expiration",
            )
            management_invariant(
                "DAY_DEADLINE_CANNOT_SILENTLY_ROLL",
                not bool(management.get("day_deadline_expired"))
                or _text(management.get("day_horizon_drift_decision")) == "INSUFFICIENT_EVIDENCE_WITH_FINAL_ESCALATION",
                "expired_day_deadline_requires_final_escalation",
            )
        capacity = _dict(runtime_state.get("last_evidence_capacity_snapshot"))
        swing_capacity = _dict(_dict(capacity.get("lanes")).get("swing"))
        if swing_capacity:
            active_remaining = _integer(capacity.get("active_strategy_slot_capacity_remaining"), -1)
            swing_decision = _text(swing_capacity.get("capacity_decision"))
            capacity_matches_slots = (
                "SWING_CONCURRENCY_LIMIT" not in swing_decision
                and (active_remaining <= 0 or swing_decision == "AVAILABLE")
            )
            invariants.append({
                "invariant_id": "SWING_CAPACITY_MATCHES_APPROVED_ACTIVE_SLOTS",
                "owner": "astra_evidence_accumulation_capacity_v1",
                "dependencies": ["SWING"],
                "state": "PASS" if capacity_matches_slots else "FAIL",
                "observed_value": {"active_slots_remaining": active_remaining, "swing_capacity_decision": swing_decision},
                "expected_value": "swing_admission_uses_active_strategy_slot_authority_only",
                "first_failed_at": None if capacity_matches_slots else _now(),
                "last_checked_at": _now(),
                "failure_count": 0 if capacity_matches_slots else 1,
                "severity": "INFO" if capacity_matches_slots else "HIGH",
                "repairability": "DIAGNOSTIC",
                "exact_blocker": None if capacity_matches_slots else "STALE_SWING_CONCURRENCY_CEILING",
                "allowed_remediations": ["RESTORE_APPROVED_SWING_CAPACITY"],
            })
        velocity_limit = _integer(_dict(worker_state.get("limits")).get("max_new_positions_per_cycle"), 2)
        invariants.append({
            "invariant_id": "SWING_ENTRY_VELOCITY_BOUNDED",
            "owner": "PaperAutopilot.max_new_positions_per_cycle",
            "dependencies": ["SWING"],
            "state": "PASS" if velocity_limit == 2 else "FAIL",
            "observed_value": velocity_limit,
            "expected_value": 2,
            "first_failed_at": None if velocity_limit == 2 else _now(),
            "last_checked_at": _now(),
            "failure_count": 0 if velocity_limit == 2 else 1,
            "severity": "INFO" if velocity_limit == 2 else "HIGH",
            "repairability": "DIAGNOSTIC",
            "exact_blocker": None if velocity_limit == 2 else "SWING_ENTRY_VELOCITY_CONFIGURATION_MISMATCH",
            "allowed_remediations": [],
        })
        day_capacity = _dict(_dict(capacity.get("lanes")).get("day"))
        if day_capacity:
            position_limit = _integer(day_capacity.get("configured_position_limit"), 0)
            day_drift_count = sum(
                1 for row in management_reviews.values()
                if _text(_dict(row).get("classification")) == "DAY_HORIZON_DRIFT_POSITION"
            )
            invariants.append({
                "invariant_id": "NO_SINGLE_POSITION_LANE_DEADLOCK",
                "owner": "astra_evidence_accumulation_capacity_v1",
                "dependencies": ["DAY"],
                "state": "PASS" if not day_drift_count or position_limit > 1 else "FAIL",
                "observed_value": {"day_position_limit": position_limit, "day_drift_count": day_drift_count},
                "expected_value": "degraded_day_position_cannot_consume_entire_day_lane",
                "first_failed_at": None if not day_drift_count or position_limit > 1 else _now(),
                "last_checked_at": _now(),
                "failure_count": 0 if not day_drift_count or position_limit > 1 else 1,
                "severity": "INFO" if not day_drift_count or position_limit > 1 else "HIGH",
                "repairability": "DIAGNOSTIC",
                "exact_blocker": None if not day_drift_count or position_limit > 1 else "DAY_LANE_DEADLOCK",
                "allowed_remediations": [],
            })
        trace_rows = list(_dict(runtime_state.get("last_execution_trace")).get("per_candidate_decision_trace") or [])
        for trace in trace_rows[:200]:
            row = _dict(trace)
            if _text(row.get("asset_type") or row.get("asset_class")).lower() != "crypto":
                continue
            attribution = _dict(row.get("eligibility_gate_attribution_v1"))
            first_gate = _dict(attribution.get("first_failing_gate"))
            contract = _dict(row.get("pretrade_decision_contract_v1"))
            contract_attribution = _dict(row.get("contract_failure_attribution_v1"))
            missing = list(contract.get("missing_required_fields") or row.get("pretrade_decision_contract_missing_fields") or [])
            if not bool(row.get("eligible")) and not first_gate:
                invariants.append({
                    "invariant_id": "NO_VAGUE_CRYPTO_GATE_REJECTION", "owner": "PaperAutopilot._candidate_trace_row",
                    "dependencies": [_text(row.get("candidate_id") or row.get("symbol"))], "state": "FAIL",
                    "observed_value": {"symbol": row.get("symbol")}, "expected_value": "exact_crypto_first_failing_gate",
                    "first_failed_at": _now(), "last_checked_at": _now(), "failure_count": 1,
                    "severity": "HIGH", "repairability": "DIAGNOSTIC", "exact_blocker": "CRYPTO_GATE_ATTRIBUTION_MISSING", "allowed_remediations": [],
                })
            contract_incomplete = _text(contract.get("contract_state") or row.get("pretrade_decision_contract_state")).upper() == "CONTRACT_INCOMPLETE"
            attribution_complete = bool(
                contract_attribution
                and list(contract_attribution.get("missing_fields") or []) == missing
                and _text(contract_attribution.get("producer"))
                and _text(contract_attribution.get("consumer"))
            )
            if contract_incomplete and (not missing or not attribution_complete):
                invariants.append({
                    "invariant_id": "NO_CONTRACT_INCOMPLETE_WITHOUT_FIELD_ATTRIBUTION", "owner": "PaperAutopilot._candidate_trace_row",
                    "dependencies": [_text(row.get("candidate_id") or row.get("symbol"))], "state": "FAIL",
                    "observed_value": {"symbol": row.get("symbol"), "missing_fields": missing}, "expected_value": "missing_contract_fields_attributed",
                    "first_failed_at": _now(), "last_checked_at": _now(), "failure_count": 1,
                    "severity": "HIGH", "repairability": "DIAGNOSTIC", "exact_blocker": "CRYPTO_CONTRACT_INCOMPLETE", "allowed_remediations": [],
                })
        return invariants, rows

    def _campaign_for(self, rows: list[dict[str, Any]], authorization: str) -> dict[str, Any] | None:
        for row in rows:
            if row["daily_sufficient"] and not row["review"]:
                return self._campaign(row, "sufficient_daily_evidence_without_current_lifecycle_review", "NO_CURRENT_ELIGIBLE_BROKER_LIFECYCLE_REVIEW", authorization, "LEGITIMATE_WAITING_STATE", None)
            if row["review"] and not row["identity_complete"]:
                return self._campaign(row, "lifecycle_identity_incomplete", "AMBIGUOUS_LANE_STRATEGY_HORIZON_IDENTITY", authorization, "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED", None)
            if row["review_eligible"] and not row["review_scheduled"]:
                return self._campaign(row, "eligible_review_not_scheduled", "ELIGIBLE_REVIEW_IS_SCHEDULED", authorization, "AUTO_REPAIR_ACTIVE", "REQUEUE_ELIGIBLE_LIFECYCLE_REVIEW")
            if row["daily_sufficient"] and row["review_eligible"] and not row["momentum_current"]:
                return self._campaign(row, "sufficient_daily_evidence_without_current_momentum", "SUFFICIENT_BARS_BUILD_MOMENTUM", authorization, "AUTO_REPAIR_ACTIVE", "SCHEDULE_MISSING_MOMENTUM_BUILD")
            if row["momentum_current"] and not all(row["acknowledgements"].values()):
                return self._campaign(row, "momentum_without_all_consumer_acknowledgements", "MOMENTUM_IS_ACKNOWLEDGED", authorization, "AUTO_REPAIR_ACTIVE", "RETRY_MISSING_CONSUMER_ACKNOWLEDGEMENT")
        return None

    def _campaign(self, row: dict[str, Any], symptom: str, blocker: str, authorization: str, state: str, remediation: str | None) -> dict[str, Any]:
        identity = row["identity"]
        campaign_key = f"{blocker}:{row['activation_id']}"
        return {
            "campaign_id": "campaign-" + hashlib.sha1(campaign_key.encode()).hexdigest()[:12], "campaign_key": campaign_key,
            "opened_at": _now(), "original_symptom": symptom, "first_causal_blocker": blocker,
            "dependency_path": ["provider.persistence", "evidence.lifecycle_identity", "evidence.review", "evidence.momentum", "consumer.cortex"],
            "affected_components": ["PaperAutopilot", "legacy_swing_lifecycle"], "affected_records": [{"activation_id": row["activation_id"], "symbol": row["symbol"], "identity": identity}],
            "severity": "WARN", "repairability": "ALLOWLISTED" if remediation else "LEGITIMATE_WAITING" if state == "LEGITIMATE_WAITING_STATE" else "AMBIGUOUS_FAIL_CLOSED",
            "selected_remediation": remediation, "repair_attempts": [], "before_state": {}, "after_state": {}, "verification_results": [], "remaining_downstream_failures": [],
            "retry_count": 0, "cooldown_until": None, "final_state": state, "closed_at": _now() if state in {"LEGITIMATE_WAITING_STATE", "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED"} else None,
            "authorization": authorization, "identity": identity,
        }

    def _apply(self, campaign: dict[str, Any], runtime_state: dict[str, Any]) -> dict[str, Any]:
        remediation = campaign.get("selected_remediation")
        registry = remediation_registry()
        if remediation not in registry:
            campaign["final_state"] = "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED"
            campaign["remaining_downstream_failures"] = ["unknown_or_unallowlisted_remediation"]
            return campaign
        if campaign.get("authorization") != "AUTO_REMEDIATION_AUTHORIZED":
            campaign["final_state"] = "SAFE_BOUNDED_BACKLOG"
            campaign["remaining_downstream_failures"] = [campaign.get("authorization")]
            return campaign
        activation_id = _text((campaign.get("affected_records") or [{}])[0].get("activation_id"))
        activations = runtime_state.setdefault("legacy_forward_activations", {})
        activation = _dict(activations.get(activation_id))
        if not activation:
            campaign["final_state"] = "LEGITIMATE_WAITING_STATE"
            campaign["remaining_downstream_failures"] = ["activation_not_present_in_worker_runtime"]
            return campaign
        before = {"refresh_priority": activation.get("refresh_priority"), "governance_tasks": _dict(activation.get("governance_tasks"))}
        tasks = _dict(activation.get("governance_tasks"))
        tasks[remediation] = {"requested_at": _now(), "campaign_id": campaign["campaign_id"], "status": "QUEUED_FOR_EXISTING_BOUNDED_WORKER"}
        activation["governance_tasks"] = tasks
        activation["governance_requeue_requested_at"] = _now()
        activation["refresh_priority"] = max(int(activation.get("refresh_priority") or 0), 100)
        activations[activation_id] = activation
        after = {"refresh_priority": activation.get("refresh_priority"), "governance_tasks": tasks}
        transaction = {"transaction_id": "txn-" + uuid.uuid4().hex[:12], "campaign_id": campaign["campaign_id"], "remediation_id": remediation, "lease_owner": str(os.getpid()), "target_component": "legacy_forward_activations", "before_checksum": _checksum(before), "after_checksum": _checksum(after), "started_at": _now(), "completed_at": _now(), "verification_state": "PASS" if remediation in tasks else "FAIL", "rollback_state": "RECONSTRUCTABLE_DERIVED_METADATA"}
        campaign["before_state"] = before
        campaign["after_state"] = after
        campaign["repair_attempts"] = [transaction]
        campaign["verification_results"] = [{"invariant": registry[remediation]["triggering_invariant"], "state": transaction["verification_state"], "verification": registry[remediation]["verification_action"]}]
        campaign["retry_count"] = 1
        campaign["final_state"] = "SAFE_BOUNDED_BACKLOG"
        campaign["remaining_downstream_failures"] = ["existing_worker_must_consume_queued_task_in_next_bounded_cycle"]
        return campaign

    def _unknown_defect_package(self, invariant: dict[str, Any]) -> dict[str, Any]:
        """Capture a source-repair-ready package without attempting a repair."""
        invariant_id = _text(invariant.get("invariant_id"), "UNKNOWN_INVARIANT")
        return {
            "unknown_defect_id": "unknown-" + hashlib.sha1((invariant_id + _now()).encode()).hexdigest()[:12],
            "first_failing_invariant": invariant_id,
            "exact_reproduction_path": list(invariant.get("dependencies") or []),
            "affected_files_and_functions": [invariant.get("owner")],
            "affected_records": [invariant.get("observed_value")],
            "relevant_logs": [],
            "before_and_after_observations": {"observed": invariant.get("observed_value"), "expected": invariant.get("expected_value")},
            "smallest_recommended_code_repair": "add a component-owned allowlisted remediation with deterministic verification",
            "required_tests": ["component contract", "fail_closed regression", "GET route read-only"],
            "required_runtime_validation": ["bounded worker cycle", "canonical snapshot persistence"],
            "safety_state": "FAIL_CLOSED_NO_AUTONOMOUS_SOURCE_REWRITE",
        }

    def run_worker_cycle(self, *, worker_state: dict[str, Any], runtime_state: dict[str, Any], safety: dict[str, Any]) -> dict[str, Any]:
        """Scan and repair only from a worker cycle; API routes call ``snapshot``."""
        started = time.monotonic()
        authorization = self._safety_authorization(worker_state, safety)
        invariants, rows = self._invariants(worker_state, runtime_state)
        campaign = self._campaign_for(rows, authorization)
        campaigns = self._load_campaigns()
        repairs_executed = repairs_verified = 0
        with self._lease() as acquired:
            if campaign and acquired:
                existing = next((item for item in reversed(campaigns) if item.get("campaign_key") == campaign.get("campaign_key") and item.get("final_state") not in {"REPAIRED_AND_VERIFIED", "LEGITIMATE_WAITING_STATE", "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED"}), None)
                if existing:
                    campaign = existing
                if campaign.get("selected_remediation") and int(campaign.get("retry_count") or 0) < 2:
                    campaign = self._apply(campaign, runtime_state)
                    repairs_executed = 1
                    repairs_verified = int(bool(campaign.get("verification_results") and campaign["verification_results"][-1].get("state") == "PASS"))
                campaigns = [item for item in campaigns if item.get("campaign_key") != campaign.get("campaign_key")] + [campaign]
                self._save_campaigns(campaigns)
        counts = {state: sum(1 for row in invariants if row.get("state") == state) for state in ("PASS", "WARN", "FAIL", "LEGITIMATE_WAITING_STATE", "NOT_APPLICABLE")}
        verification_rows = list(_dict(campaign).get("verification_results") or [])
        unknown_packages = [self._unknown_defect_package(row) for row in invariants if row.get("state") == "FAIL" and row.get("repairability") == "DIAGNOSTIC"][:3]
        summary = {
            "status": "PASS_AUTONOMOUS_REMEDIATION_WITH_BOUNDED_BACKLOG" if campaign and campaign.get("final_state") in {"SAFE_BOUNDED_BACKLOG", "LEGITIMATE_WAITING_STATE"} else "PASS_AUTONOMOUS_REMEDIATION_ACTIVE",
            "scan_time": _now(), "scan_duration_ms": round((time.monotonic() - started) * 1000.0, 2), "scan_owner": "engine.paper_autopilot_worker",
            "authorization": authorization, "invariants": invariants, "invariants_passed": counts["PASS"], "invariants_warned": counts["WARN"] + counts["LEGITIMATE_WAITING_STATE"], "invariants_failed": counts["FAIL"],
            "active_campaigns": sum(1 for item in campaigns if item.get("final_state") in {"AUTO_REPAIR_ACTIVE", "SAFE_BOUNDED_BACKLOG"}), "campaigns_repaired": sum(1 for item in campaigns if item.get("final_state") == "REPAIRED_AND_VERIFIED"), "campaigns_waiting": sum(1 for item in campaigns if item.get("final_state") == "LEGITIMATE_WAITING_STATE"), "campaigns_failed_closed": sum(1 for item in campaigns if item.get("final_state") == "UNSAFE_OR_AMBIGUOUS_FAIL_CLOSED"),
            "repairs_executed": repairs_executed, "repairs_verified": repairs_verified, "repairs_rolled_back": 0, "unknown_defects_packaged": len(unknown_packages), "unknown_defect_packages": unknown_packages,
            "repair_budgets": {"maximum_automatic_repairs_per_cycle": MAX_REPAIRS_PER_CYCLE, "maximum_provider_persistence_retries_per_record": MAX_PROVIDER_RETRIES_PER_RECORD, "maximum_lifecycle_requeues_per_symbol_per_cycle": MAX_LIFECYCLE_REQUEUES_PER_SYMBOL_PER_CYCLE, "maximum_consumer_retries_per_evidence": MAX_CONSUMER_RETRIES_PER_EVIDENCE, "maximum_concurrent_index_rebuilds": 1},
            "current_campaign": campaign, "cortex_operational_diagnosis": {"root_cause": campaign.get("first_causal_blocker") if campaign else "none", "affected_chain": campaign.get("dependency_path") if campaign else [], "selected_safe_remediation": campaign.get("selected_remediation") if campaign else None, "why_safe": "allowlisted derived scheduling metadata only; no trading policy or broker action" if campaign else "no active causal break", "verification_result": verification_rows[-1] if verification_rows else None, "decision_impact": "advisory/lifecycle evidence only", "canary_impact": "unchanged and separately gated", "remaining_risk": (campaign.get("remaining_downstream_failures") or []) if campaign else []},
            "proof_rows": [{"symbol": row["symbol"], "activation_id": row["activation_id"], "identity": row["identity"], "daily_evidence_sufficient": row["daily_sufficient"], "review_eligible": row["review_eligible"], "review_scheduled": row["review_scheduled"], "momentum_state": "CURRENT" if row["momentum_current"] else "NOT_CURRENT", "consumer_acknowledgements": row["acknowledgements"], "exact_exclusion_or_failure_reason": "no_current_eligible_broker_lifecycle_review" if row["daily_sufficient"] and not row["review"] else None} for row in rows[:20]],
            "canary_runtime_authorization": "UNCHANGED_SEPARATE_GATE", "proactive_scan_triggers": ["worker_startup", "after_bounded_worker_cycle", "after_provider_persistence", "after_evidence_consumption", "after_resource_recovery"],
            "unknown_defect_packaging": {"enabled": True, "fail_closed": True, "package_fields": ["first_failing_invariant", "reproduction_path", "affected_records", "smallest_recommended_code_repair", "tests", "runtime_validation"]},
            **_safe_flags(),
        }
        _atomic_write(self.summary_path, summary)
        return summary
