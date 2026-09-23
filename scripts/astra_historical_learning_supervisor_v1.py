#!/usr/bin/env python3
"""Single durable owner for bounded incremental historical learning wakeups."""
from __future__ import annotations

import argparse
import json
import os
import signal
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sys

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.astra_historical_learning_cycle_runner import HistoricalLearningCycleRunnerV1, compact_cycle_result


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE = ROOT / "state"
DEFAULT_INTERVAL_SECONDS = 300.0
PID_FILE = "astra_historical_learning_supervisor_v1.pid"
STATUS_FILE = "astra_historical_learning_supervisor_v1.json"


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def claim_pid(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        try:
            existing = int(path.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            existing = 0
        if existing and _alive(existing):
            return False
        path.unlink(missing_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(str(os.getpid()))
    return True


def release_pid(path: Path) -> None:
    try:
        if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def run_once(
    *,
    state_dir: Path = DEFAULT_STATE,
    pid_path: Path | None = None,
    status_path: Path | None = None,
    runner: HistoricalLearningCycleRunnerV1 | None = None,
) -> dict[str, Any]:
    state_dir = Path(state_dir)
    pid_path = pid_path or state_dir / PID_FILE
    status_path = status_path or state_dir / STATUS_FILE
    owned = claim_pid(pid_path)
    if not owned:
        result = {"status": "SKIP_ALREADY_RUNNING", "owner": "historical_learning_supervisor_v1", "updated_at": _now()}
        _atomic_write(status_path, result)
        return result
    try:
        active_runner = runner or HistoricalLearningCycleRunnerV1(str(state_dir))
        result = active_runner.wake_once()
        compact = compact_cycle_result(result)
        payload = {
            "schema_version": "astra_historical_learning_supervisor_v1",
            "owner": "historical_learning_supervisor_v1",
            "pid": os.getpid(),
            "runner_pid": result.get("pid") or os.getpid(),
            "status": result.get("status"),
            "last_wakeup": _now(),
            "last_result": compact,
            "resource_decision": result.get("resource_decision"),
            "source_progress": result.get("source_progress") or compact.get("source_progress") or {},
            "safety": {
                "broker_calls_added": 0,
                "broker_actions_added": 0,
                "execution_behavior_changed": False,
                "frozen_lifecycle_modified": False,
                "v10_authority_preserved": True,
            },
        }
        _atomic_write(status_path, payload)
        return payload
    finally:
        release_pid(pid_path)


def run_forever(state_dir: Path, interval_seconds: float = DEFAULT_INTERVAL_SECONDS) -> int:
    state_dir = Path(state_dir)
    pid_path = state_dir / PID_FILE
    if not claim_pid(pid_path):
        return 0
    stopped = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        runner = HistoricalLearningCycleRunnerV1(str(state_dir), interval_seconds=interval_seconds)
        while not stopped:
            result = runner.wake_once()
            compact = compact_cycle_result(result)
            _atomic_write(
                state_dir / STATUS_FILE,
                {
                    "schema_version": "astra_historical_learning_supervisor_v1",
                    "owner": "historical_learning_supervisor_v1",
                    "pid": os.getpid(),
                    "runner_pid": os.getpid(),
                    "status": result.get("status"),
                    "last_wakeup": _now(),
                    "last_result": compact,
                    "resource_decision": result.get("resource_decision"),
                    "source_progress": result.get("source_progress") or compact.get("source_progress") or {},
                    "safety": {
                        "broker_calls_added": 0,
                        "broker_actions_added": 0,
                        "execution_behavior_changed": False,
                        "frozen_lifecycle_modified": False,
                        "v10_authority_preserved": True,
                    },
                },
            )
            deadline = time.monotonic() + max(30.0, float(interval_seconds))
            while not stopped and time.monotonic() < deadline:
                time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    finally:
        release_pid(pid_path)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)
    if args.once:
        print(json.dumps(run_once(state_dir=args.state_dir), sort_keys=True, separators=(",", ":")))
        return 0
    return run_forever(args.state_dir, args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
