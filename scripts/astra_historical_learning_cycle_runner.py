#!/usr/bin/env python3
"""Standalone, deliberately thin caller for V10/V10.1 historical learning."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import signal
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from engine.astra_incremental_historical_learning_governor_v1 import (  # noqa: E402
    build_incremental_historical_learning_governor_v1,
    run_incremental_historical_learning_cycle_v1,
)


VERSION = "1.0.0"
DEFAULT_INTERVAL_SECONDS = 300.0
STATUS_FILE = "astra_historical_learning_cycle_runner_v1.json"
LOCK_FILE = "astra_historical_learning_cycle_runner_v1.lock"
SUCCESSFUL_CYCLE_STATES = {"READY", "COMPLETE", "NO_OUTCOME_DATA"}
SAFETY = {
    "provider_calls_added": 0,
    "broker_calls_added": 0,
    "broker_actions_added": 0,
    "llm_calls_added": 0,
    "execution_behavior_changed": False,
    "frozen_lifecycle_modified": False,
    "v10_authority_preserved": True,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def compact_cycle_result(result: Mapping[str, Any]) -> dict[str, Any]:
    """Keep runner logs/status operational, never a copy of V10's full payload."""
    cycle = result.get("cycle") if isinstance(result.get("cycle"), Mapping) else {}
    partitions = cycle.get("partitions_processed") if isinstance(cycle.get("partitions_processed"), list) else []
    partition = dict(partitions[0]) if partitions and isinstance(partitions[0], Mapping) else {}
    throughput = result.get("throughput") if isinstance(result.get("throughput"), Mapping) else {}
    return {
        "timestamp": _now(),
        "status": result.get("status"),
        "resource_decision": result.get("resource_decision"),
        "throughput_mode": throughput.get("mode"),
        "cycles_invoked": result.get("cycles_invoked", 0),
        "partition_id": partition.get("partition_id"),
        "source": partition.get("source"),
        "rows_examined": partition.get("rows_examined"),
        "bytes_read": partition.get("bytes_read"),
        "outcome_links_added": partition.get("outcome_linked_count"),
        "aggregate_updates": partition.get("aggregate_updates"),
        "duration_seconds": partition.get("duration_seconds"),
        "reason": result.get("reason") or cycle.get("reason"),
    }


class HistoricalLearningCycleRunnerV1:
    """Wake V10 at a conservative cadence without owning any learning policy."""

    def __init__(
        self,
        state_dir: str = "state",
        interval_seconds: float | None = None,
        *,
        status_builder: Callable[..., dict[str, Any]] = build_incremental_historical_learning_governor_v1,
        cycle_runner: Callable[..., dict[str, Any]] = run_incremental_historical_learning_cycle_v1,
    ) -> None:
        self.state = Path(state_dir)
        configured = os.getenv("ASTRA_HISTORICAL_LEARNING_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
        self.interval_seconds = max(30.0, float(interval_seconds if interval_seconds is not None else configured))
        self.status_builder = status_builder
        self.cycle_runner = cycle_runner
        self.started_at = _now()

    def _status_path(self) -> Path:
        return self.state / STATUS_FILE

    def _lock_path(self) -> Path:
        return self.state / LOCK_FILE

    def _write_status(self, result: Mapping[str, Any]) -> None:
        previous: dict[str, Any] = {}
        try:
            loaded = json.loads(self._status_path().read_text(encoding="utf-8"))
            previous = dict(loaded) if isinstance(loaded, dict) else {}
        except (OSError, ValueError, TypeError):
            pass
        compact = compact_cycle_result(result)
        status = str(compact.get("status") or "UNKNOWN")
        totals = dict(previous.get("totals") or {})
        totals["attempted"] = int(totals.get("attempted") or 0) + 1
        if status in SUCCESSFUL_CYCLE_STATES:
            totals["completed"] = int(totals.get("completed") or 0) + 1
        elif status.startswith("DEFER") or status == "SKIP_ALREADY_RUNNING":
            totals["deferred"] = int(totals.get("deferred") or 0) + 1
        elif status == "ERROR":
            totals["errors"] = int(totals.get("errors") or 0) + 1
        payload = {
            "version": VERSION,
            "runner_status": status,
            "pid": os.getpid(),
            "started_at": previous.get("started_at") or self.started_at,
            "last_wakeup": _now(),
            "last_cycle_result": compact,
            "last_successful_cycle": compact if status in SUCCESSFUL_CYCLE_STATES else previous.get("last_successful_cycle"),
            "totals": totals,
            **SAFETY,
        }
        _atomic_write(self._status_path(), payload)

    def wake_once(self, resource_facts: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Run no more than one V10 cycle, and only when V10 says RUN."""
        self.state.mkdir(parents=True, exist_ok=True)
        handle = self._lock_path().open("a+", encoding="utf-8")
        try:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                result = {"status": "SKIP_ALREADY_RUNNING", "reason": "RUNNER_LOCK_HELD", **SAFETY}
                self._write_status(result)
                return result
            status = self.status_builder(str(self.state), resource_facts)
            decision = dict(status.get("resource_decision") or {})
            if decision.get("decision") != "RUN":
                result = {
                    "status": "DEFERRED_RESOURCE_GOVERNOR",
                    "resource_decision": decision,
                    "throughput": status.get("throughput"),
                    "cycles_invoked": 0,
                    **SAFETY,
                }
            else:
                # No max_rows/max_bytes arguments: V10 remains the sole budget owner.
                cycle = self.cycle_runner(str(self.state), resource_facts=resource_facts)
                result = {
                    "status": str(cycle.get("status") or "ERROR"),
                    "resource_decision": decision,
                    "throughput": cycle.get("throughput") or status.get("throughput"),
                    "cycles_invoked": 1,
                    "cycle": cycle,
                    **SAFETY,
                }
            self._write_status(result)
            return result
        finally:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()

    def run_forever(self) -> int:
        stopped = False

        def stop(_signum: int, _frame: object) -> None:
            nonlocal stopped
            stopped = True

        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while not stopped:
            self.wake_once()
            deadline = time.monotonic() + self.interval_seconds
            while not stopped and time.monotonic() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Safe standalone caller for Astra V10 historical learning.")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--interval", type=float, default=None, help="Seconds between V10 wakeups; default is env or 300.")
    parser.add_argument("--once", action="store_true", help="Run one governor-authorized wakeup, then exit.")
    args = parser.parse_args(argv)
    runner = HistoricalLearningCycleRunnerV1(args.state_dir, args.interval)
    if args.once:
        print(json.dumps(compact_cycle_result(runner.wake_once()), sort_keys=True))
        return 0
    return runner.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
