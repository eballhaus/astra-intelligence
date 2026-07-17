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
from pathlib import Path
from typing import Any

from engine.astra_runtime_governance_v1 import (
    ROOT,
    STATE,
    WORKER_STATE_PATH,
    RuntimeLimits,
    WorkerLease,
    read_snapshot,
    resource_snapshot,
    rotate_log,
    utc_now,
    write_snapshot,
)


class PaperAutopilotWorker:
    def __init__(self, autopilot: Any, *, once: bool = False) -> None:
        self.autopilot = autopilot
        self.once = once
        self.limits = RuntimeLimits.from_env()
        self.lease = WorkerLease()
        self.stop_requested = False
        self.cycle_count = int(read_snapshot().get("cycle_count") or 0)
        self.cooldown_until = 0.0

    def _base_state(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0.0",
            "worker_instance_id": self.lease.instance_id,
            "worker_generation_id": self.lease.generation_id,
            "process_id": os.getpid(),
            "parent_process_id": os.getppid(),
            "process_role": "PAPER_AUTOPILOT_WORKER",
            "started_at": utc_now(),
            "heartbeat_at": utc_now(),
            "cycle_id": "",
            "cycle_state": "IDLE",
            "cycle_elapsed_seconds": 0.0,
            "cycle_stop_reason": "",
            "cursor": "",
            "symbols_due": 0,
            "symbols_attempted": 0,
            "symbols_completed": 0,
            "symbols_deferred": 0,
            "provider_requests": 0,
            "pages_consumed": 0,
            "records_persisted": 0,
            "momentum_records_built": 0,
            "resource_pause_state": "RESOURCE_NORMAL",
            "last_error": "",
            "last_error_at": "",
            "next_cycle_at": utc_now(),
            "limits": self.limits.__dict__,
            "canonical_state_path": str(WORKER_STATE_PATH),
            "full_store_scans": 0,
            "provider_calls_used_by_status": 0,
            "broker_actions_used_by_status": 0,
        }

    def _publish(self, **updates: Any) -> dict[str, Any]:
        current = read_snapshot()
        state = self._base_state() if not current or current.get("worker_generation_id") != self.lease.generation_id else current
        state.update(updates)
        state["heartbeat_at"] = utc_now()
        worker_pid = int(state.get("process_id") or os.getpid())
        state["resource"] = resource_snapshot(worker_pid=worker_pid)
        write_elapsed = write_snapshot(state)
        state["state_write_elapsed_seconds"] = round(write_elapsed, 4)
        # Compatibility snapshots retained for current diagnostics; both are
        # derived solely from this canonical record.
        compatibility = {
            "pid": worker_pid,
            "running": not self.stop_requested,
            "updated_at": state["heartbeat_at"],
            "last_cycle_utc": state.get("last_cycle_completed_at") or "",
            "worker_generation_id": self.lease.generation_id,
            "worker_cycle_started_at": state.get("last_cycle_started_at") or "",
            "worker_cycle_completed_at": state.get("last_cycle_completed_at") or "",
            "worker_cycle_phase": state.get("cycle_state"),
            "last_error": state.get("last_error") or "",
            "interval_seconds": self.limits.minimum_sleep_between_cycles_seconds,
            "autopilot_enabled": bool(getattr(self.autopilot, "_enabled", False)),
            "process_role": "PAPER_AUTOPILOT_WORKER",
        }
        write_snapshot(compatibility, STATE / "paper_worker_heartbeat.json")
        write_snapshot({"pid": worker_pid, "worker_generation_id": self.lease.generation_id, "process_role": "PAPER_AUTOPILOT_WORKER"}, STATE / "paper_worker.pid")
        return state

    def _on_signal(self, _signum: int, _frame: Any) -> None:
        self.stop_requested = True

    def _bounded_cycle(self) -> None:
        started = time.monotonic()
        cycle_id = f"cycle-{self.cycle_count + 1}-{int(time.time())}"
        before = resource_snapshot(worker_pid=os.getpid())
        resource_state = str(before.get("resource_state") or "RESOURCE_NORMAL")
        if resource_state in {"RESOURCE_HIGH_PAUSE", "MEMORY_PRESSURE_PAUSE"}:
            self.cooldown_until = time.monotonic() + self.limits.recovery_cooldown_seconds
            self._publish(
                cycle_id=cycle_id,
                cycle_state="PAUSED_MEMORY_PRESSURE" if resource_state == "MEMORY_PRESSURE_PAUSE" else "PAUSED_HIGH_LOAD",
                cycle_stop_reason=str(before.get("resource_reason") or "resource_pause"),
                resource_pause_state=resource_state,
                next_cycle_at=utc_now(),
            )
            return
        if time.monotonic() < self.cooldown_until:
            self._publish(cycle_id=cycle_id, cycle_state="CHECKPOINTED", cycle_stop_reason="RECOVERY_COOLDOWN", resource_pause_state="RECOVERY_COOLDOWN")
            return

        original_max_stocks = getattr(self.autopilot, "max_stocks", self.limits.maximum_symbols_per_cycle)
        symbol_budget = 1 if resource_state == "RESOURCE_ELEVATED" else self.limits.maximum_symbols_per_cycle
        # This is a per-process cycle budget, not a persistent strategy setting.
        self.autopilot.max_stocks = min(int(original_max_stocks), symbol_budget)
        self._publish(cycle_id=cycle_id, cycle_state="ACTIVE_BOUNDED", last_cycle_started_at=utc_now(), resource_pause_state=resource_state)
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
            self._publish(
                cycle_id=cycle_id,
                cycle_state=state,
                cycle_stop_reason=stop_reason,
                cycle_elapsed_seconds=round(elapsed, 3),
                last_cycle_completed_at=utc_now(),
                last_checkpoint_at=utc_now(),
                cycle_count=self.cycle_count,
                cursor=str(scheduler.get("round_robin_cursor") or ""),
                symbols_due=int(scheduler.get("symbols_due") or 0),
                symbols_attempted=min(symbol_budget, int(scheduler.get("symbols_processed") or 0)),
                symbols_completed=min(symbol_budget, int(scheduler.get("symbols_processed") or 0)),
                symbols_deferred=int(scheduler.get("symbols_deferred") or 0),
                provider_requests=min(self.limits.maximum_provider_requests_per_cycle, int((market.get("families") or {}).get("HISTORICAL_BARS", {}).get("request_count") or 0)),
                pages_consumed=min(self.limits.maximum_pages_per_symbol * self.limits.maximum_symbols_per_cycle, int(market.get("pages_consumed") or 0)),
                records_persisted=int(market.get("records_persisted") or 0),
                momentum_records_built=int(market.get("momentum_records_built") or 0),
                last_error=str(trace.get("worker_cycle_error") or "")[:240],
                next_cycle_at=utc_now(),
            )
        except Exception as exc:  # Fail closed and leave the API unaffected.
            self._publish(cycle_id=cycle_id, cycle_state="FAILED_SAFE", cycle_stop_reason="worker_cycle_exception", last_error=str(exc)[:240], last_error_at=utc_now())
        finally:
            self.autopilot.max_stocks = original_max_stocks

    def run(self) -> int:
        if not self.lease.acquire():
            # A rejected contender must never alter the live owner's state.
            # Its exit code is the duplicate signal consumed by supervision.
            return 2
        signal.signal(signal.SIGTERM, self._on_signal)
        signal.signal(signal.SIGINT, self._on_signal)
        self._publish(cycle_state="IDLE", ownership_state="SINGLE_WORKER_ACTIVE")
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
            self._publish(cycle_state="CHECKPOINTED", cycle_stop_reason="worker_stopped", ownership_state="NO_WORKER_ACTIVE")
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
