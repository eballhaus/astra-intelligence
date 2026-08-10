"""The sole mutable owner for bounded PaperAutopilot cycles.

The module never binds an HTTP port.  It is deliberately small: the existing
PaperAutopilot engine remains the execution owner while this process provides
single-writer ownership, resource pauses, and an atomic status snapshot.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.request
from typing import Any

from engine.astra_runtime_governance_v1 import (
    STATE,
    WORKER_STATE_PATH,
    RuntimeLimits,
    WorkerLease,
    advance_resource_policy,
    read_snapshot,
    resource_snapshot,
    rotate_log,
    utc_now,
    write_snapshot,
)
from engine.astra_continuous_governance_v1 import ContinuousGovernanceV1
from engine.astra_governance_coverage_consolidation_v1 import (
    COMPONENT_ID,
    AstraGovernanceCoverageConsolidationV1,
)
from engine.crypto_operational_integrity_readiness_v1 import CryptoOperationalIntegrityReadinessV1
from engine.shadow_profit_loss_protection_validation_v1 import ShadowProfitLossProtectionValidationV1
from engine.astra_canonical_truth_registry_v1 import fact_envelope_v1
from engine.astra_truth_arbitration_v1 import TruthContradictionRegistryV1, arbitrate_truth_claims_v1, read_canonical_open_crypto_positions
from engine.astra_continuous_system_integrity_scanner_v1 import ContinuousSystemIntegrityScannerV1
from engine.astra_crypto_market_data_capability_matrix_v1 import CryptoMarketDataCapabilityMatrixV1
from engine.astra_multilane_completion_matrix_v1 import AstraMultilaneCompletionMatrixV1
from engine.astra_operating_health_contract_v1 import AstraOperatingHealthContractV1
from engine.astra_evidence_accumulation_capacity_v1 import canonical_candidate_capacity_fact
from engine.candidate_execution_integrity_v1 import derive_crypto_horizon_evidence_v1


# A cycle may contain bounded local persistence work that lasts longer than
# the nominal scan budget.  Publish liveness independently of that work so a
# live canonical worker is never misreported as absent or stale.
ACTIVE_CYCLE_HEARTBEAT_SECONDS = 5.0


class PaperAutopilotWorker:
    def __init__(self, autopilot: Any, *, once: bool = False) -> None:
        self.autopilot = autopilot
        self.once = once
        # Ensure the autopilot has the crypto candidate function set, even when
        # the worker starts independently of the server factory.
        if not callable(getattr(autopilot, "get_crypto_candidate_rows_fn", None)):
            try:
                from server_extend import _crypto_operational_candidate_rows_v3
                autopilot.get_crypto_candidate_rows_fn = _crypto_operational_candidate_rows_v3
            except Exception:
                pass
        self.limits = RuntimeLimits.from_env()
        self.lease = WorkerLease()
        self.stop_requested = False
        self._terminal_exit_reason = ""
        self.cycle_count = int(read_snapshot().get("cycle_count") or 0)
        self.previous_cursor = str(read_snapshot().get("cursor") or "")
        self.resource_policy = dict(read_snapshot().get("resource_policy") or {})
        self.continuous_governance = ContinuousGovernanceV1(STATE)
        self.governance_coverage = AstraGovernanceCoverageConsolidationV1(STATE)
        self.crypto_operational_integrity = CryptoOperationalIntegrityReadinessV1(STATE)
        self.shadow_profit_loss_protection = ShadowProfitLossProtectionValidationV1(STATE)
        self.truth_contradictions = TruthContradictionRegistryV1(STATE)
        self.system_integrity_scanner = ContinuousSystemIntegrityScannerV1(STATE)
        self.crypto_market_data_matrix = CryptoMarketDataCapabilityMatrixV1(STATE)
        self.multilane_completion_matrix = AstraMultilaneCompletionMatrixV1(STATE)
        self.operating_health_contract = AstraOperatingHealthContractV1(STATE)

    def _base_state(self) -> dict[str, Any]:
        previous = read_snapshot()
        return {
            "schema_version": "1.0.0",
            "state_version": "1.1.0",
            "worker_instance_id": self.lease.instance_id,
            "worker_generation_id": self.lease.generation_id,
            "process_id": os.getpid(),
            "parent_process_id": os.getppid(),
            "process_role": "PAPER_AUTOPILOT_WORKER",
            "active_worker_present": True,
            "active_worker_pid": os.getpid(),
            "active_worker_instance_id": self.lease.instance_id,
            "active_worker_generation_id": self.lease.generation_id,
            "last_known_worker_pid": previous.get("last_known_worker_pid") or previous.get("process_id"),
            "last_known_worker_instance_id": previous.get("last_known_worker_instance_id") or previous.get("worker_instance_id"),
            "last_known_worker_generation_id": previous.get("last_known_worker_generation_id") or previous.get("worker_generation_id"),
            "last_known_worker_cycle_id": previous.get("last_known_worker_cycle_id") or previous.get("cycle_id"),
            "last_known_worker_stopped_at": previous.get("last_known_worker_stopped_at"),
            "last_known_worker_exit_reason": previous.get("last_known_worker_exit_reason") or previous.get("cycle_stop_reason"),
            "started_at": utc_now(),
            "heartbeat_at": utc_now(),
            "cycle_id": "",
            "cycle_state": "IDLE",
            "cycle_elapsed_seconds": 0.0,
            "cycle_stop_reason": "",
            "cursor": self.previous_cursor,
            "symbols_due": 0,
            "symbols_attempted": 0,
            "symbols_completed": 0,
            "symbols_deferred": 0,
            "provider_requests": 0,
            "pages_consumed": 0,
            "records_persisted": 0,
            "momentum_records_built": 0,
            "daily_sufficient_count": 0,
            "daily_insufficient_count": 0,
            "daily_failed_count": 0,
            "downstream_acknowledgements": {},
            "recovered_daily_symbols": [],
            "resource_pause_state": "RESOURCE_NORMAL",
            "resource_policy": self.resource_policy,
            "last_error": "",
            "last_error_at": "",
            "next_cycle_at": utc_now(),
            "limits": self.limits.__dict__,
            "canonical_state_path": str(WORKER_STATE_PATH),
            "full_store_scans": 0,
            "provider_calls_used_by_status": 0,
            "broker_actions_used_by_status": 0,
        }

    def _publish(self, *, resource: dict[str, Any] | None = None, resource_policy: dict[str, Any] | None = None, **updates: Any) -> dict[str, Any]:
        current = read_snapshot()
        state = self._base_state() if not current or current.get("worker_generation_id") != self.lease.generation_id else current
        state.update(updates)
        state["heartbeat_at"] = utc_now()
        if state.get("active_worker_present") is not False:
            state["active_worker_present"] = True
            state["active_worker_pid"] = os.getpid()
            state["active_worker_instance_id"] = self.lease.instance_id
            state["active_worker_generation_id"] = self.lease.generation_id
        state["resource"] = dict(resource or state.get("resource") or resource_snapshot(worker_pid=os.getpid()))
        state["resource_policy"] = dict(resource_policy or self.resource_policy)
        state["resource_state"] = state["resource"].get("resource_state")
        state["host_load_observed"] = state["resource"].get("host_load_1m")
        state["worker_memory_observed"] = (state["resource"].get("worker_process") or {}).get("memory_mb")
        # Persist the execution owner's state with this snapshot.  Assigning
        # it after write_snapshot made a healthy enabled worker look disabled
        # to read-only status consumers until a later cycle rewrote the file.
        state["autopilot_enabled"] = bool(getattr(self.autopilot, "_enabled", False))
        write_elapsed = write_snapshot(state)
        state["state_write_elapsed_seconds"] = round(write_elapsed, 4)
        return state

    def _sync_autopilot_progress(
        self,
        phase: str,
        *,
        cycle_started_at: str = "",
        cycle_completed_at: str = "",
        error: str = "",
        error_type: str = "",
        persist: bool = False,
    ) -> None:
        """Bridge the isolated worker's real lifecycle into engine state.

        The wrapper owns the process lease and the engine owns the retirement
        state.  Without this bridge, an old in-process-thread generation can
        remain in ``paper_autopilot_state.json`` even while this process is
        healthy, making a live worker look stalled.
        """
        recorder = getattr(self.autopilot, "record_external_worker_progress", None)
        if callable(recorder):
            recorder(
                worker_generation_id=self.lease.generation_id,
                process_id=os.getpid(),
                parent_process_id=os.getppid(),
                cycle_count=self.cycle_count,
                phase=phase,
                cycle_started_at=cycle_started_at,
                cycle_completed_at=cycle_completed_at,
                error=error,
                error_type=error_type,
                persist=persist,
            )
            return
        # Compatibility fallback for a deliberately minimal test double.
        runtime = getattr(self.autopilot, "_runtime_state", None)
        if isinstance(runtime, dict):
            runtime.update({
                "worker_generation_id": self.lease.generation_id,
                "worker_process_id": os.getpid(),
                "worker_parent_process_id": os.getppid(),
                "worker_cycle_count": self.cycle_count,
                "worker_cycle_phase": phase,
                "worker_heartbeat_at": utc_now(),
            })
            if cycle_started_at:
                runtime["worker_cycle_started_at"] = cycle_started_at
            if cycle_completed_at:
                runtime["worker_cycle_completed_at"] = cycle_completed_at

    def _publish_active_cycle_heartbeat(
        self,
        *,
        cycle_id: str,
        cycle_started_monotonic: float,
        stop_event: threading.Event,
    ) -> None:
        """Refresh only worker-control-plane liveness during a long cycle.

        This thread never invokes the autopilot, broker, provider, or engine
        state writer.  It owns only the already-canonical worker runtime
        snapshot and exits before cycle completion can publish its final
        state, preventing an old heartbeat from overwriting completion.
        """
        while not stop_event.wait(ACTIVE_CYCLE_HEARTBEAT_SECONDS):
            current = read_snapshot()
            if str(current.get("worker_generation_id") or "") != self.lease.generation_id:
                return
            runtime = getattr(self.autopilot, "_runtime_state", {})
            phase = str(runtime.get("worker_cycle_phase") or "external_cycle_active") if isinstance(runtime, dict) else "external_cycle_active"
            current.update({
                "heartbeat_at": utc_now(),
                "active_cycle_heartbeat_at": utc_now(),
                "cycle_id": cycle_id,
                "cycle_state": "ACTIVE_BOUNDED",
                "cycle_heartbeat_phase": phase[:96],
                "cycle_elapsed_seconds": round(time.monotonic() - cycle_started_monotonic, 3),
                "active_worker_present": True,
                "active_worker_pid": os.getpid(),
                "active_worker_instance_id": self.lease.instance_id,
                "active_worker_generation_id": self.lease.generation_id,
            })
            write_snapshot(current)

    def _backend_health_latency_ms(self) -> float | None:
        """Bounded internal health probe; never calls a provider or broker."""
        host = os.getenv("ASTRA_BACKEND_HOST", "127.0.0.1")
        port = os.getenv("ASTRA_BACKEND_PORT", "8000")
        started = time.monotonic()
        try:
            with urllib.request.urlopen(f"http://{host}:{port}/api/health", timeout=1.5) as response:
                if int(getattr(response, "status", 0) or 0) != 200:
                    return None
            return round((time.monotonic() - started) * 1000.0, 2)
        except Exception:
            return None

    def _sample_resource(self) -> tuple[dict[str, Any], dict[str, Any]]:
        sample = resource_snapshot(
            worker_pid=os.getpid(),
            backend_health_latency_ms=self._backend_health_latency_ms(),
            require_complete=True,
        )
        self.resource_policy = advance_resource_policy(self.resource_policy, sample, limits=self.limits)
        sample["resource_state"] = self.resource_policy["resource_state"]
        sample["resource_reason"] = self.resource_policy["resource_transition_reason"]
        sample["resource_decision"] = self.resource_policy["resource_decision"]
        return sample, self.resource_policy

    def _evidence_summary(self) -> dict[str, Any]:
        """Summarize already-produced worker evidence without new reads or calls."""
        runtime = dict(getattr(self.autopilot, "_runtime_state", {}).get("legacy_swing_canary") or {})
        records = dict(runtime.get("market_records") or getattr(self.autopilot, "_runtime_state", {}).get("legacy_swing_market_evidence") or {})
        reviews = dict(runtime.get("reviews") or {})
        activity = dict(runtime.get("market_activity") or getattr(self.autopilot, "_runtime_state", {}).get("legacy_swing_market_activity") or {})
        current_symbols = {str(symbol or "").upper() for symbol in list(activity.get("symbols_completed") or [])}
        bounded_records = [
            (activation_id, bundle_raw)
            for activation_id, bundle_raw in records.items()
            if str(dict((bundle_raw or {}).get("HISTORICAL_BARS_DAILY") or {}).get("symbol") or "").upper() in current_symbols
        ]
        if not bounded_records:
            bounded_records = list(records.items())
        sufficient = insufficient = failed = momentum = 0
        recovered: list[dict[str, Any]] = []
        acknowledgements = {"direct_evidence": 0, "forward_value": 0, "profit_capture": 0, "direct_confirmation": 0, "lifecycle": 0}
        for activation_id, bundle_raw in bounded_records[: self.limits.maximum_downstream_symbols_per_cycle]:
            review = dict(reviews.get(activation_id) or {})
            daily = dict((bundle_raw or {}).get("HISTORICAL_BARS_DAILY") or {})
            required = int(daily.get("required_completed_bars") or 15)
            completed = int(daily.get("records_valid") or 0)
            quality = str(daily.get("quality_state") or "")
            evidence = dict((review.get("required_evidence") or {}).get("MOMENTUM") or {})
            current = evidence.get("status") == "CURRENT"
            if quality == "CURRENT_SUFFICIENT" and completed >= required:
                sufficient += 1
            elif str(daily.get("response_state") or "").upper() not in {"", "SUCCESS", "EMPTY_RESPONSE"}:
                failed += 1
            else:
                insufficient += 1
            if current:
                momentum += 1
                recovered.append({"symbol": daily.get("symbol") or review.get("symbol"), "canonical_series_id": daily.get("record_id"), "momentum_record_id": evidence.get("record_id"), "completed_sessions": completed, "provider": daily.get("provider"), "worker_cycle_id": "", "worker_generation_id": self.lease.generation_id})
            coverage = dict(review.get("direct_evidence_coverage") or {})
            acknowledgements["direct_evidence"] += int(bool(coverage.get("required_evidence_complete")))
            acknowledgements["forward_value"] += int(bool(review.get("forward_value_review") or review.get("forward_value")))
            acknowledgements["profit_capture"] += int(bool(review.get("profit_capture") or review.get("profit_capture_intelligence")))
            acknowledgements["direct_confirmation"] += int(bool(review.get("direct_confirmation_state")))
            acknowledgements["lifecycle"] += int(bool(review.get("lifecycle_decision") or review.get("lifecycle_status")))
        acknowledgements["all_required_consumers_acknowledged"] = bool(momentum and all(value > 0 for value in acknowledgements.values()))
        return {"daily_sufficient_count": sufficient, "daily_insufficient_count": insufficient, "daily_failed_count": failed, "momentum_records_built": momentum, "downstream_acknowledgements": acknowledgements, "recovered_daily_symbols": recovered}

    def _canonical_crypto_matrix_candidates(
        self,
        *,
        candidate_rows: list[dict[str, Any]],
        evaluated_rows: list[dict[str, Any]],
        capacity_snapshot: dict[str, Any],
        open_symbols: set[str],
    ) -> list[dict[str, Any]]:
        """Project cached crypto rows through the existing final trace owner.

        ``CryptoOperationalIntegrityReadinessV1`` intentionally reports its
        pre-execution guard.  The completion matrix needs the earlier
        PaperAutopilot decision gate as well, otherwise a guard alias can hide
        the actual first candidate rejection.  This calls no provider, broker,
        order, or reservation path and is diagnostic-only.
        """
        by_symbol = {
            str(row.get("symbol") or "").upper(): dict(row)
            for row in evaluated_rows if isinstance(row, dict)
        }
        trace_builder = getattr(self.autopilot, "_candidate_trace_row", None)
        capacity_reader = getattr(self.autopilot, "_current_execution_capacities", None)
        if not callable(trace_builder) or not callable(capacity_reader):
            return list(by_symbol.values())
        try:
            capacities = dict(capacity_reader() or {})
        except Exception:
            return list(by_symbol.values())
        stock_capacity = int(capacities.get("stock_capacity") or 0)
        crypto_capacity = int(capacities.get("crypto_capacity") or 0)
        total_capacity = int(capacities.get("total_capacity") or 0)
        reconciliation_current = bool(capacity_snapshot.get("broker_positions_fetch_ok"))
        projected: list[dict[str, Any]] = []
        for raw in candidate_rows[:25]:
            if not isinstance(raw, dict):
                continue
            candidate = {**dict(raw), "lane_id": "CRYPTO", "asset_class": "crypto", "asset_type": "crypto"}
            symbol = str(candidate.get("symbol") or candidate.get("ticker") or "").upper()
            merged = dict(by_symbol.get(symbol) or candidate)
            # Integrity readiness rows are intentionally pre-execution records.
            # They do not always include the final candidate fields consumed by
            # PaperAutopilot qualification.  Projecting such a row would create
            # a synthetic CONTRACT_INCOMPLETE blocker, rather than preserving
            # the real earlier freshness/activation gate that stopped it.
            if not candidate.get("entry_commitment") or not (
                candidate.get("candidate_generated_at") or candidate.get("generated_at")
            ):
                merged["canonical_execution_projection_owner"] = "PRE_EXECUTION_INTEGRITY_ONLY"
                merged["pre_execution_integrity_blocker"] = dict(merged.get("first_causal_blocker") or {})
                projected.append(merged)
                continue
            try:
                trace, _allowed, _reason, _meta = trace_builder(
                    candidate,
                    open_syms=set(open_symbols),
                    stock_capacity=stock_capacity,
                    crypto_capacity=crypto_capacity,
                    total_capacity=total_capacity,
                    internal_open_syms=set(open_symbols),
                    broker_open_syms=set(open_symbols),
                    broker_reconciliation_active=reconciliation_current,
                    capacity_snapshot=capacity_snapshot,
                    current_candidates=candidate_rows[:25],
                )
            except Exception:
                projected.append(merged)
                continue
            attribution = dict(trace.get("eligibility_gate_attribution_v1") or {})
            if dict(attribution.get("first_failing_gate") or {}).get("code"):
                merged["eligibility_gate_attribution_v1"] = attribution
                merged["first_failing_gate"] = dict(attribution.get("first_failing_gate") or {})
                merged["canonical_execution_projection_owner"] = "PaperAutopilot._candidate_trace_row"
                merged["pre_execution_integrity_blocker"] = dict(merged.get("first_causal_blocker") or {})
            projected.append(merged)
        return projected or list(by_symbol.values())

    def _on_signal(self, _signum: int, _frame: Any) -> None:
        self._terminal_exit_reason = f"worker_signal_{int(_signum)}"
        self.stop_requested = True

    def _run_continuous_governance(self) -> dict[str, Any]:
        """Run the bounded remediation scanner after worker-owned state exists.

        The scanner cannot contact providers or brokers.  If it queues a
        derived scheduler repair, persist the existing autopilot state through
        its atomic writer so the next normal bounded cycle can consume it.
        """
        worker_state = read_snapshot()
        safety = dict(getattr(self.autopilot, "_alpaca_safety_snapshot", lambda: {})() or {})
        crypto_activation = {}
        crypto_rows: list[dict[str, Any]] = []
        throughput_snapshot: dict[str, Any] = {}
        try:
            activation_builder = getattr(self.autopilot, "_crypto_paper_activation_status", None)
            crypto_activation = dict(activation_builder() or {}) if callable(activation_builder) else {}
            candidate_source = getattr(self.autopilot, "get_crypto_candidate_rows_fn", None)
            crypto_rows = [dict(row) for row in (candidate_source() or []) if isinstance(row, dict)] if callable(candidate_source) else []
            # Reuse the producer/consumer contract normalizer before every
            # worker-owned diagnostic consumes cached crypto candidates. This
            # cannot rank, promote, or execute a candidate; it only preserves
            # explicit evidence or an insufficient-evidence outcome.
            crypto_rows = [{**row, **derive_crypto_horizon_evidence_v1(row)} for row in crypto_rows]
        except Exception:
            # The crypto lane remains independently fail-closed.  A missing
            # cached source cannot affect equity work or create a candidate.
            crypto_rows = []
        try:
            ledger = getattr(self.autopilot, "execution_trace_ledger", None)
            if ledger is not None:
                throughput_snapshot = {
                    "summary": dict(ledger.summary() or {}),
                    "window": dict(ledger.window_summary(days=7) or {}),
                    "owner": "existing_lane_execution_trace_ledger_v1",
                }
        except Exception:
            # Governance remains available even if an optional diagnostic
            # index has not yet been created by the worker.
            throughput_snapshot = {"status": "UNAVAILABLE_FAIL_CLOSED"}
        if not self.governance_coverage.component_enabled(COMPONENT_ID):
            # A certification rollback can isolate this optional diagnostic
            # hook without touching the execution engine or canonical truth.
            result = {**self.continuous_governance.snapshot(), "status": "COMPONENT_ISOLATED_FAIL_CLOSED", "repairs_executed": 0, "repairs_verified": 0}
        else:
            result = self.continuous_governance.run_worker_cycle(
                worker_state=worker_state,
                runtime_state=getattr(self.autopilot, "_runtime_state", {}),
                safety=safety,
            )
        if int(result.get("repairs_executed") or 0) > 0:
            save = getattr(self.autopilot, "_save_state_file", None)
            if callable(save):
                save()
        # Coverage is a separate, metadata-only owner.  It consumes the
        # committed governance outcome and current worker state; it cannot
        # call a provider, broker, or alter the autopilot decision policy.
        coverage = self.governance_coverage.run_worker_cycle(
            continuous=result,
            runtime={**worker_state, "broker_truth_throughput": throughput_snapshot},
            preflight={
                "paper_mode_verified": bool(safety.get("paper_mode_verified")),
                "broker_live_endpoint_allowed": bool(safety.get("broker_live_endpoint_allowed")),
            },
            crypto={
                "activation": crypto_activation,
                "natural_candidate_count": sum(1 for row in crypto_rows if not bool(row.get("operational_probe_only"))),
                "cached_candidate_count": len(crypto_rows),
                "lineage_isolated": all(str(row.get("asset_class") or "crypto").lower() == "crypto" for row in crypto_rows),
            },
        )
        # These are bounded cache/state compositions. They deliberately reuse
        # the cycle's existing data and never submit, cancel, or probe orders.
        crypto_integrity: dict[str, Any] = {}
        shadow_protection: dict[str, Any] = {}
        truth_arbitration: dict[str, Any] = {}
        try:
            # Compatibility rows are retained only as a rejected diagnostic
            # claim. Active crypto reconciliation uses canonical SQLite rows.
            positions = [dict(row) for row in (self.autopilot.paper_positions() or []) if isinstance(row, dict)]
            # The worker must inspect the same position store used by the
            # executing engine.  ``paper_autopilot.db`` is a historical
            # compatibility artifact in some deployments and may be empty.
            canonical_position_db = str(getattr(self.autopilot, "db_path", "") or (STATE / "paper_autopilot.db"))
            canonical_crypto_positions = read_canonical_open_crypto_positions(canonical_position_db)
            broad_crypto_rows = [row for row in positions if str(row.get("asset_class") or row.get("asset_type") or "").lower() in {"crypto", "cryptocurrency"}]
            broad_crypto_count = len(broad_crypto_rows)
            capacity = dict(getattr(self.autopilot, "_runtime_state", {}).get("last_evidence_capacity_snapshot") or {})
            broker_crypto_count = int(capacity.get("crypto_open_positions") or 0)
            rejected_diagnostic_claim = {
                "fact_id": "LOCAL_OPEN_CRYPTO_POSITION_COUNT", "value": broad_crypto_count,
                "claimed_scope": "all crypto-labeled compatibility rows",
                "source_owner": "PAPER_AUTOPILOT.paper_positions", "source_type": "adapter",
                "canonical": False, "source_timestamp": utc_now(),
                "consumer": "diagnostic-only compatibility observation",
                "rejection_reason": "prohibited substitute; not an active-position fact claim",
            }
            claims = [
                fact_envelope_v1("LOCAL_OPEN_CRYPTO_POSITION_COUNT", len(canonical_crypto_positions), snapshot_id=str(capacity.get("snapshot_id") or ""), exclusions=["historical", "diagnostic", "reconstructed", "closed", "unfilled"]),
                fact_envelope_v1("BROKER_OPEN_CRYPTO_POSITION_COUNT", broker_crypto_count, snapshot_id=str(capacity.get("snapshot_id") or "")),
            ]
            truth_arbitration = arbitrate_truth_claims_v1(claims)
            truth_arbitration["rejected_diagnostic_claims"] = [rejected_diagnostic_claim]
            truth_arbitration["contradiction_registry"] = self.truth_contradictions.observe(list(truth_arbitration.get("contradictions") or []))
            getattr(self.autopilot, "_runtime_state", {})["truth_arbitration_v1"] = dict(truth_arbitration)
            lane = {
                "activation_requested": crypto_activation.get("activation_requested"),
                "paper_crypto_enabled": crypto_activation.get("paper_crypto_enabled"),
                "paper_mode_verified": safety.get("paper_mode_verified"),
                "kill_switch_enabled": crypto_activation.get("kill_switch_enabled"),
                "capital_configured": crypto_activation.get("capital_configured"),
                "capital_limit": crypto_activation.get("capital_limit"),
                "crypto_day_trade_capacity": crypto_activation.get("crypto_day_trade_capacity"),
                "crypto_short_swing_capacity": crypto_activation.get("crypto_short_swing_capacity"),
                # Legacy fields are reported for compatibility only. Candidate
                # integrity receives the canonical fact below.
                "day_trade_capacity_available": crypto_activation.get("day_trade_capacity_available"),
                "short_swing_capacity_available": crypto_activation.get("short_swing_capacity_available"),
                "legacy_capacity_aliases_diagnostic_only": True,
                "canonical_capacity_fact": canonical_candidate_capacity_fact(
                    capacity,
                    lane_id="CRYPTO",
                    open_symbols=[row.get("symbol") for row in canonical_crypto_positions],
                ),
                "lane_state": crypto_activation.get("lane_state"),
                "broker_reconciliation_ok": bool(capacity.get("broker_positions_fetch_ok")) and broker_crypto_count == len(canonical_crypto_positions),
                "broker_reconciliation_status": "CURRENT_MATCHED" if broker_crypto_count == len(canonical_crypto_positions) else "COUNT_MISMATCH_FAIL_CLOSED",
                "canonical_local_position_source": f"{canonical_position_db}.paper_positions",
                "canonical_local_position_query_scope": "status=OPEN AND asset_type=crypto",
                "canonical_local_open_crypto_count": len(canonical_crypto_positions),
                "noncanonical_rows_observed": broad_crypto_count,
                "noncanonical_rows_excluded": broad_crypto_count,
                "historical_rows_excluded": 0,
                "diagnostic_rows_excluded": 0,
                "reconstructed_rows_excluded": 0,
                "closed_rows_excluded": 0,
                "unfilled_rows_excluded": 0,
                "local_crypto_open_count": len(canonical_crypto_positions), "broker_crypto_open_count": broker_crypto_count,
            }
            broker = getattr(self.autopilot, "alpaca_paper_broker", None)
            cached_capability = getattr(broker, "cached_crypto_capability", None)
            capability = dict(cached_capability() or {}) if callable(cached_capability) else {}
            if not capability.get("crypto_trading_supported") and isinstance(crypto_activation.get("capability"), dict):
                # The activation owner may already hold the same canonical
                # capability payload.  Never reconstruct it from booleans.
                capability = dict(crypto_activation.get("capability") or capability)
            lifecycle_rows = self.shadow_profit_loss_protection.load_bounded_lifecycle_rows()
            crypto_integrity = self.crypto_operational_integrity.build(
                lane=lane, capability=capability, candidates=crypto_rows,
                open_positions=canonical_crypto_positions, pending_orders=[], lifecycle_rows=lifecycle_rows, buying_power=None,
            )
            self.crypto_operational_integrity.write_snapshot(crypto_integrity)
            crypto_matrix = self.crypto_market_data_matrix.build(
                capability=capability,
                ranking_snapshot=dict(getattr(self.autopilot, "_runtime_state", {}).get("crypto_rankings_snapshot_v1") or {}),
            )
            self.crypto_market_data_matrix.write(crypto_matrix)
            shadow_protection = self.shadow_profit_loss_protection.build(
                lifecycle_rows, positions,
            )
            self.shadow_profit_loss_protection.write_snapshot(shadow_protection)
            # This uses only the current worker's committed candidate and
            # trace evidence. It is diagnostic-only and cannot alter a gate,
            # a lifecycle, or any broker-facing behavior.
            # The completion matrix must consume the evaluated integrity
            # contract, not raw ranking rows. That preserves each candidate's
            # ordered first causal blocker through readiness and governance.
            evaluated_crypto_rows = [
                dict(row) for row in ((crypto_integrity.get("pair_eligibility") or {}).get("evaluated_candidates") or [])
                if isinstance(row, dict)
            ]
            runtime = getattr(self.autopilot, "_runtime_state", {})
            execution_trace = dict(runtime.get("last_execution_trace") or {})
            partial = dict((runtime.get("last_cycle_summary") or {}).get("partial_candidate_microphase") or {})
            target_lane = str(partial.get("target_lane") or "").upper()
            lane_observations = {
                lane: {"observation_state": "NOT_EVALUATED_THIS_PARTIAL_CYCLE", "observation_scope": "bounded_partial_cycle"}
                for lane in ("SWING", "DAY", "SCALP", "CRYPTO")
            }
            if target_lane in lane_observations and partial.get("microphase_completed"):
                lane_observations[target_lane] = {
                    "observation_state": "CURRENT_PARTIAL_EVALUATION",
                    "observation_scope": "bounded_candidate_integrity_only",
                    "candidate_count": partial.get("candidates_evaluated", partial.get("candidate_rows_loaded", 0)),
                    "fresh_candidate_count": partial.get("fresh", 0),
                    # The microphase never performs PaperAutopilot selection
                    # or order construction. Keep its preliminary count
                    # separate from executable eligibility.
                    "preliminary_eligible_candidate_count": partial.get("eligible", 0),
                    "first_causal_blocker": partial.get("first_causal_blocker"),
                    "exact_blocker_reason": partial.get("exact_blocker_reason"),
                }
            matrix_crypto_rows = self._canonical_crypto_matrix_candidates(
                candidate_rows=crypto_rows,
                evaluated_rows=evaluated_crypto_rows,
                capacity_snapshot=capacity,
                open_symbols={str(row.get("symbol") or "").upper() for row in canonical_crypto_positions if row.get("symbol")},
            )
            completion_candidates = [*matrix_crypto_rows, *[dict(row) for row in execution_trace.get("per_candidate_decision_trace") or [] if isinstance(row, dict)]]
            capacity_lanes = dict((capacity.get("lanes") or {}))
            active_positions_by_lane = {
                lane: dict(capacity_lanes.get(lane.lower()) or {}).get("raw_broker_position_count", 0)
                for lane in ("SWING", "DAY", "SCALP", "CRYPTO")
            }
            managed_capacity_positions_by_lane = {
                lane: dict(capacity_lanes.get(lane.lower()) or {}).get("positions_used", 0)
                for lane in ("SWING", "DAY", "SCALP", "CRYPTO")
            }
            legacy_excluded_positions_by_lane = {
                lane: dict(capacity_lanes.get(lane.lower()) or {}).get("legacy_excluded_position_count", 0)
                for lane in ("SWING", "DAY", "SCALP", "CRYPTO")
            }
            multilane_completion = self.multilane_completion_matrix.build(
                candidate_rows=completion_candidates,
                execution_trace=execution_trace,
                crypto_readiness=crypto_integrity,
                shadow=shadow_protection,
                source_freshness=str(execution_trace.get("candidate_freshness") or "UNKNOWN"),
                lane_observations=lane_observations,
                active_positions_by_lane=active_positions_by_lane,
                managed_capacity_positions_by_lane=managed_capacity_positions_by_lane,
                legacy_excluded_positions_by_lane=legacy_excluded_positions_by_lane,
            )
            self.multilane_completion_matrix.write(multilane_completion)
        except Exception:
            # Optional diagnostics fail closed and cannot interrupt the owner
            # worker or alter the trading cycle.
            crypto_integrity = {"status": "UNAVAILABLE_FAIL_CLOSED"}
            crypto_matrix = {"status": "UNAVAILABLE_FAIL_CLOSED"}
            shadow_protection = {"status": "UNAVAILABLE_FAIL_CLOSED"}
            truth_arbitration = {"status": "UNAVAILABLE_FAIL_CLOSED"}
            multilane_completion = {"status": "UNAVAILABLE_FAIL_CLOSED"}
        # A changed causal fingerprint is a bounded reason to scan now. The
        # canonical worker remains the only scanner owner; unchanged evidence
        # continues to use the normal low-frequency Sentinel interval.
        runtime = getattr(self.autopilot, "_runtime_state", {})
        current_blockers = [
            {
                "symbol": row.get("symbol"),
                "gate": (row.get("first_causal_blocker") or {}).get("gate"),
                "status": (row.get("first_causal_blocker") or {}).get("status"),
            }
            for row in ((crypto_integrity.get("pair_eligibility") or {}).get("evaluated_candidates") or [])
            if isinstance(row, dict) and isinstance(row.get("first_causal_blocker"), dict)
        ][:8]
        fingerprint = json.dumps(current_blockers, sort_keys=True, separators=(",", ":"))
        targeted_reasons: list[str] = []
        if fingerprint and fingerprint != str(runtime.get("crypto_sentinel_blocker_fingerprint_v1") or ""):
            runtime["crypto_sentinel_blocker_fingerprint_v1"] = fingerprint
            targeted_reasons = list(dict.fromkeys(
                f"crypto_first_causal_blocker:{row['gate']}" for row in current_blockers[:3] if row.get("gate")
            ))
        # This scanner owns only bounded state diagnostics. It consumes the
        # facts already gathered by this worker and cannot reach providers,
        # brokers, LLMs, order paths, or mutable lifecycle truth.
        integrity_scan = self.system_integrity_scanner.run_if_due(
            worker_state=worker_state,
            runtime_state=runtime,
            safety=safety,
            context={
                "truth_arbitration": truth_arbitration,
                "continuous_governance": result,
                "crypto_integrity": crypto_integrity,
                "shadow_protection": shadow_protection,
                "quote_handoffs": list(getattr(self.autopilot, "_runtime_state", {}).get("crypto_quote_handoffs_v1") or (getattr(self.autopilot, "_runtime_state", {}).get("crypto_rankings_snapshot_v1") or {}).get("crypto_quote_handoffs_v1") or [])[:20],
                "crypto_ranking_snapshot": dict(getattr(self.autopilot, "_runtime_state", {}).get("crypto_rankings_snapshot_v1") or {}),
                "crypto_market_data_matrix": crypto_matrix,
                "multilane_completion_matrix": multilane_completion,
                "position_lane_horizon_recovery": dict(runtime.get("position_lane_horizon_recovery_v1") or {}),
                "historical_reconciliation_ownership_collisions": dict(getattr(self.autopilot, "_historical_reconciliation_ownership_collisions_v1", lambda: {})() or {}),
                "entry_lane_horizon_integrity": dict(getattr(self.autopilot, "entry_lane_horizon_ledger", None).snapshot() if getattr(self.autopilot, "entry_lane_horizon_ledger", None) is not None else {}),
                "provider_consumption_telemetry": dict(runtime.get("provider_consumption_telemetry_v1") or {}),
                "position_evidence_completeness": dict(runtime.get("position_evidence_completeness_v1") or {}),
                "unified_position_advisory": dict(runtime.get("unified_position_advisory_v1") or {}),
                "copilot_position_advisory_handoff": dict(runtime.get("copilot_position_advisory_handoff_v1") or {}),
                "shadow_exit_diagnostics": dict(runtime.get("shadow_exit_diagnostics_v1") or {}),
                "shadow_exit_analysis_outputs": dict(runtime.get("shadow_exit_analysis_outputs_v1") or {}),
                "shadow_exit_performance": dict(runtime.get("shadow_exit_performance_v1") or {}),
                "canonical_capacity_fact": dict(lane.get("canonical_capacity_fact") or {}),
                "targeted_reasons": targeted_reasons,
                "get_side_effects": 0,
            },
        )
        # One compact worker-written control-plane view keeps lane truth,
        # Sentinel, Governance, and Cortex evidence aligned for GET consumers.
        # It only composes the current cycle's committed records.
        truth_rows = [dict(row) for row in (runtime.get("broker_truth_records_v1") or []) if isinstance(row, dict)]
        learning_rows = [dict(row) for row in (runtime.get("canonical_lifecycle_lessons_v1") or []) if isinstance(row, dict)]
        operating_health = self.operating_health_contract.build(
            multilane=multilane_completion,
            worker_state=worker_state,
            continuous=result,
            sentinel=integrity_scan,
            cortex=dict(integrity_scan.get("cortex_summary") or {}),
            truth_records=truth_rows,
            learning_records=learning_rows,
        )
        self.operating_health_contract.write(operating_health)
        runtime["astra_operating_health_contract_v1"] = dict(operating_health)
        getattr(self.autopilot, "_runtime_state", {})["system_integrity_scanner_v1"] = dict(integrity_scan)
        self._publish(continuous_governance={
            "status": result.get("status"),
            "authorization": result.get("authorization"),
            "current_campaign_id": dict(result.get("current_campaign") or {}).get("campaign_id"),
            "first_causal_blocker": dict(result.get("current_campaign") or {}).get("first_causal_blocker"),
            "repairs_executed": result.get("repairs_executed"),
            "repairs_verified": result.get("repairs_verified"),
            "coverage_status": coverage.get("status"),
            "coverage_certification": dict((coverage.get("post_deployment_certifications") or [{}])[0]).get("certification_state"),
            "crypto_operational_integrity_status": crypto_integrity.get("status"),
            "shadow_profit_loss_protection_status": shadow_protection.get("status"),
            "truth_arbitration_status": truth_arbitration.get("status"),
            "truth_contradiction_count": len(truth_arbitration.get("contradictions") or []),
            "system_integrity_status": integrity_scan.get("status"),
            "system_integrity_root_cause_count": len(integrity_scan.get("active_root_causes") or []),
            "multilane_completion_status": multilane_completion.get("status"),
        })
        return result

    def _bounded_cycle(self) -> None:
        started = time.monotonic()
        cycle_id = f"cycle-{self.cycle_count + 1}-{int(time.time())}"
        # The API process only writes the guarded enable decision.  The
        # isolated worker consumes that durable switch before each cycle so an
        # API-local instance cannot claim activation the execution owner did
        # not receive.  This performs no broker/provider action and fails
        # closed if the control record is unreadable.
        control_sync = {
            "ok": False,
            "autopilot_enabled": False,
            "control_state_sync": "UNSUPPORTED_FAIL_CLOSED",
        }
        refresh_control = getattr(self.autopilot, "refresh_control_state_from_disk", None)
        if callable(refresh_control):
            try:
                control_sync = dict(refresh_control() or control_sync)
            except Exception as exc:
                if hasattr(self.autopilot, "_enabled"):
                    self.autopilot._enabled = False
                control_sync = {
                    "ok": False,
                    "autopilot_enabled": False,
                    "control_state_sync": "FAILED_CLOSED",
                    "control_state_error": str(exc)[:160],
                }
        self._publish(paper_autopilot_control_sync=control_sync)
        before, policy = self._sample_resource()
        resource_state = str(before.get("resource_state") or "RESOURCE_NORMAL")
        if resource_state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_UNKNOWN_FAIL_CLOSED"}:
            self._sync_autopilot_progress("external_cycle_resource_paused", persist=True)
            self._publish(
                resource=before,
                resource_policy=policy,
                cycle_id=cycle_id,
                cycle_state="PAUSED_MEMORY_PRESSURE" if resource_state == "RESOURCE_MEMORY_PAUSE" else "PAUSED_API_LATENCY" if resource_state == "RESOURCE_API_LATENCY_PAUSE" else "PAUSED_RESOURCE_UNKNOWN" if resource_state == "RESOURCE_UNKNOWN_FAIL_CLOSED" else "PAUSED_HIGH_LOAD",
                cycle_stop_reason=str(before.get("resource_reason") or "resource_pause"),
                resource_pause_state=resource_state,
                symbols_due=0,
                symbols_attempted=0,
                symbols_completed=0,
                symbols_deferred=0,
                provider_requests=0,
                pages_consumed=0,
                records_persisted=0,
                next_cycle_at=utc_now(),
            )
            self._run_continuous_governance()
            return
        if resource_state == "RESOURCE_RECOVERY_COOLDOWN":
            self._sync_autopilot_progress("external_cycle_recovery_cooldown", persist=True)
            self._publish(
                resource=before,
                resource_policy=policy,
                cycle_id=cycle_id,
                cycle_state="CHECKPOINTED",
                cycle_stop_reason="RECOVERY_COOLDOWN",
                resource_pause_state="RECOVERY_COOLDOWN",
                symbols_due=0,
                symbols_attempted=0,
                symbols_completed=0,
                symbols_deferred=0,
                provider_requests=0,
                pages_consumed=0,
                records_persisted=0,
            )
            self._run_continuous_governance()
            return

        original_max_stocks = getattr(self.autopilot, "max_stocks", self.limits.maximum_symbols_per_cycle)
        symbol_budget = 1 if resource_state == "RESOURCE_ELEVATED" or policy.get("resume_mode") == "RESUME_ONE_SYMBOL" else self.limits.maximum_symbols_per_cycle
        # This is a per-process cycle budget, not a persistent strategy setting.
        self.autopilot.max_stocks = min(int(original_max_stocks), symbol_budget)
        cycle_started_at = utc_now()
        self._sync_autopilot_progress("external_cycle_active", cycle_started_at=cycle_started_at, persist=True)
        self._publish(resource=before, resource_policy=policy, cycle_id=cycle_id, cycle_state="ACTIVE_BOUNDED", last_cycle_started_at=cycle_started_at, resource_pause_state=resource_state)
        heartbeat_stop = threading.Event()
        heartbeat_thread = threading.Thread(
            target=self._publish_active_cycle_heartbeat,
            kwargs={
                "cycle_id": cycle_id,
                "cycle_started_monotonic": started,
                "stop_event": heartbeat_stop,
            },
            name="paper-autopilot-cycle-heartbeat",
            daemon=True,
        )
        heartbeat_thread.start()
        try:
            result = dict(self.autopilot.run_cycle() or {})
            elapsed = time.monotonic() - started
            trace = dict(getattr(self.autopilot, "_runtime_state", {}).get("last_execution_trace") or {})
            market = dict((result.get("legacy_swing_observation") or {}).get("market_activity") or {})
            scheduler = dict(market.get("scheduler") or {})
            stop_reason = "COMPLETE"
            state = "COMPLETE"
            if elapsed >= self.limits.maximum_cycle_elapsed_seconds:
                state, stop_reason = "PARTIAL_TIME_LIMIT", "maximum_cycle_elapsed_seconds"
            elif str(market.get("cycle_state") or "").startswith("CYCLE_PARTIAL"):
                state, stop_reason = "PARTIAL_SYMBOL_LIMIT", str(market.get("cycle_state"))
            self.cycle_count += 1
            if policy.get("resume_mode") == "RESUME_ONE_SYMBOL":
                policy = {**policy, "resume_mode": "RESUME_NORMAL_BOUNDED"}
                self.resource_policy = policy
            completed_at = utc_now()
            self._sync_autopilot_progress("external_cycle_completed", cycle_completed_at=completed_at, persist=True)
            self._publish(
                resource=before,
                resource_policy=policy,
                cycle_id=cycle_id,
                cycle_state=state,
                cycle_stop_reason=stop_reason,
                cycle_elapsed_seconds=round(elapsed, 3),
                last_cycle_completed_at=completed_at,
                last_checkpoint_at=completed_at,
                cycle_count=self.cycle_count,
                cursor=str(scheduler.get("round_robin_cursor") or ""),
                symbols_due=int(scheduler.get("symbols_due") or 0),
                symbols_attempted=min(symbol_budget, len(list(market.get("symbols_attempted") or []))),
                symbols_completed=min(symbol_budget, len(list(market.get("symbols_completed") or []))),
                symbols_deferred=len(list(market.get("symbols_deferred") or [])),
                provider_requests=min(self.limits.maximum_provider_requests_per_cycle, int(market.get("provider_requests_this_cycle") or 0)),
                pages_consumed=min(self.limits.maximum_pages_per_symbol * symbol_budget, int(market.get("pages_consumed_this_cycle") or 0)),
                records_persisted=int(market.get("records_persisted_this_cycle") or 0),
                **self._evidence_summary(),
                last_error=str(trace.get("worker_cycle_error") or "")[:240],
                next_cycle_at=utc_now(),
            )
            self._run_continuous_governance()
        except Exception as exc:  # Fail closed and leave the API unaffected.
            self._sync_autopilot_progress(
                "external_cycle_failed",
                error=str(exc)[:180],
                error_type=type(exc).__name__,
                persist=True,
            )
            self._publish(resource=before, resource_policy=policy, cycle_id=cycle_id, cycle_state="FAILED_SAFE", cycle_stop_reason="worker_cycle_exception", last_error=str(exc)[:240], last_error_at=utc_now())
            self._run_continuous_governance()
        finally:
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=ACTIVE_CYCLE_HEARTBEAT_SECONDS + 1.0)
            self.autopilot.max_stocks = original_max_stocks

    def run(self) -> int:
        if not self.lease.acquire():
            # A rejected contender must never alter the live owner's state.
            # Its exit code is the duplicate signal consumed by supervision.
            return 2
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, self._on_signal)
        initial_resource, initial_policy = self._sample_resource()
        self._sync_autopilot_progress("external_worker_started", persist=True)
        self._publish(resource=initial_resource, resource_policy=initial_policy, cycle_state="IDLE", ownership_state="SINGLE_WORKER_ACTIVE")
        self._run_continuous_governance()
        try:
            while not self.stop_requested:
                self._bounded_cycle()
                if self.once:
                    break
                deadline = time.monotonic() + self.limits.minimum_sleep_between_cycles_seconds
                while not self.stop_requested and time.monotonic() < deadline:
                    self._publish(next_cycle_at=utc_now())
                    time.sleep(min(5.0, self.limits.minimum_sleep_between_cycles_seconds))
        except BaseException as exc:
            # This outer boundary covers failures before or between bounded
            # cycles.  Record a sanitized durable cause before releasing the
            # lease; it never changes broker or trading state.
            self._terminal_exit_reason = f"worker_terminal_exception:{type(exc).__name__}"
            try:
                self._publish(
                    cycle_state="FAILED_SAFE",
                    cycle_stop_reason="worker_terminal_exception",
                    last_error=str(exc)[:240],
                    last_error_at=utc_now(),
                    worker_terminal_cause=self._terminal_exit_reason,
                )
            except Exception:
                pass
            raise
        finally:
            self.stop_requested = True
            last_cycle = read_snapshot()
            self._publish(
                cycle_state="CHECKPOINTED",
                cycle_stop_reason="worker_stopped",
                ownership_state="NO_WORKER_ACTIVE",
                active_worker_present=False,
                active_worker_pid=None,
                active_worker_instance_id=None,
                active_worker_generation_id=None,
                last_known_worker_pid=os.getpid(),
                last_known_worker_instance_id=self.lease.instance_id,
                last_known_worker_generation_id=self.lease.generation_id,
                last_known_worker_cycle_id=last_cycle.get("cycle_id"),
                last_known_worker_stopped_at=utc_now(),
                last_known_worker_exit_reason=self._terminal_exit_reason or "worker_stopped",
                worker_terminal_cause=self._terminal_exit_reason or "worker_stopped",
            )
            self.lease.release()
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Astra bounded PaperAutopilot worker")
    parser.add_argument("--once", action="store_true", help="run one bounded worker cycle then exit")
    args = parser.parse_args(argv)
    if os.getenv("ASTRA_PROCESS_ROLE", "").strip().lower() != "worker":
        print("ASTRA_PROCESS_ROLE=worker is required; refusing to run mutable worker", file=sys.stderr)
        return 64
    rotate_log(STATE / "worker.log")
    # Import after the role guard.  server_extend must never start a worker in
    # an API role; this worker explicitly owns the existing engine instance.
    from server_extend import PAPER_AUTOPILOT, _ensure_paper_autopilot_started

    _ensure_paper_autopilot_started()
    return PaperAutopilotWorker(PAPER_AUTOPILOT, once=args.once).run()


if __name__ == "__main__":
    raise SystemExit(main())
