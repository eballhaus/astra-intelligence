"""The sole mutable owner for bounded PaperAutopilot cycles.

The module never binds an HTTP port.  It is deliberately small: the existing
PaperAutopilot engine remains the execution owner while this process provides
single-writer ownership, resource pauses, and an atomic status snapshot.
"""
from __future__ import annotations

import argparse
import os
import signal
import sys
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


class PaperAutopilotWorker:
    def __init__(self, autopilot: Any, *, once: bool = False) -> None:
        self.autopilot = autopilot
        self.once = once
        self.limits = RuntimeLimits.from_env()
        self.lease = WorkerLease()
        self.stop_requested = False
        self.cycle_count = int(read_snapshot().get("cycle_count") or 0)
        self.previous_cursor = str(read_snapshot().get("cursor") or "")
        self.resource_policy = dict(read_snapshot().get("resource_policy") or {})
        self.continuous_governance = ContinuousGovernanceV1(STATE)

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
        write_elapsed = write_snapshot(state)
        state["state_write_elapsed_seconds"] = round(write_elapsed, 4)
        state["autopilot_enabled"] = bool(getattr(self.autopilot, "_enabled", False))
        return state

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

    def _on_signal(self, _signum: int, _frame: Any) -> None:
        self.stop_requested = True

    def _run_continuous_governance(self) -> dict[str, Any]:
        """Run the bounded remediation scanner after worker-owned state exists.

        The scanner cannot contact providers or brokers.  If it queues a
        derived scheduler repair, persist the existing autopilot state through
        its atomic writer so the next normal bounded cycle can consume it.
        """
        worker_state = read_snapshot()
        safety = dict(getattr(self.autopilot, "_alpaca_safety_snapshot", lambda: {})() or {})
        result = self.continuous_governance.run_worker_cycle(
            worker_state=worker_state,
            runtime_state=getattr(self.autopilot, "_runtime_state", {}),
            safety=safety,
        )
        if int(result.get("repairs_executed") or 0) > 0:
            save = getattr(self.autopilot, "_save_state_file", None)
            if callable(save):
                save()
        self._publish(continuous_governance={
            "status": result.get("status"),
            "authorization": result.get("authorization"),
            "current_campaign_id": dict(result.get("current_campaign") or {}).get("campaign_id"),
            "first_causal_blocker": dict(result.get("current_campaign") or {}).get("first_causal_blocker"),
            "repairs_executed": result.get("repairs_executed"),
            "repairs_verified": result.get("repairs_verified"),
        })
        return result

    def _bounded_cycle(self) -> None:
        started = time.monotonic()
        cycle_id = f"cycle-{self.cycle_count + 1}-{int(time.time())}"
        before, policy = self._sample_resource()
        resource_state = str(before.get("resource_state") or "RESOURCE_NORMAL")
        if resource_state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_UNKNOWN_FAIL_CLOSED"}:
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
        self._publish(resource=before, resource_policy=policy, cycle_id=cycle_id, cycle_state="ACTIVE_BOUNDED", last_cycle_started_at=utc_now(), resource_pause_state=resource_state)
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
            self._publish(
                resource=before,
                resource_policy=policy,
                cycle_id=cycle_id,
                cycle_state=state,
                cycle_stop_reason=stop_reason,
                cycle_elapsed_seconds=round(elapsed, 3),
                last_cycle_completed_at=utc_now(),
                last_checkpoint_at=utc_now(),
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
            self._publish(resource=before, resource_policy=policy, cycle_id=cycle_id, cycle_state="FAILED_SAFE", cycle_stop_reason="worker_cycle_exception", last_error=str(exc)[:240], last_error_at=utc_now())
            self._run_continuous_governance()
        finally:
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
                last_known_worker_exit_reason="worker_stopped",
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
