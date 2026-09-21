#!/usr/bin/env python3
"""Durable, resource-aware coordinator for bounded local history work."""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.astra_local_historical_gap_runner_v1 import resource_gate
from scripts.astra_historical_data_infrastructure_v1 import durable_write

STATE_ROOT = Path("/Users/Shared/AstraRuntime/state")
SUPERVISOR_ROOT = "historical_context_phase2_v1/local_gap_runner_v1"
DEFAULT_PID = Path("/tmp/astra_history_overnight.pid")
DEFAULT_STATUS = Path("/tmp/astra_history_overnight_status.json")
DEFAULT_LOG = Path("/tmp/astra_history_overnight.log")
CHECKPOINT_NAME = "overnight_supervisor_checkpoint.json"
LANES = ("news-proof", "macro", "analyst", "microstructure")
POLL_SECONDS = 60


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    durable_write(path, (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode())


def _read_json(path: Path, default: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else (default or {})
    except (OSError, ValueError, TypeError):
        return default or {}


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _claim_pid(path: Path) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
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


def _release_pid(path: Path) -> None:
    try:
        if int(path.read_text(encoding="utf-8").strip()) == os.getpid():
            path.unlink(missing_ok=True)
    except (OSError, ValueError):
        pass


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{now_iso()} {message}\n")


def _checkpoint_path(state_dir: Path) -> Path:
    return state_dir / SUPERVISOR_ROOT / CHECKPOINT_NAME


def _runner_command(lane: str, state_dir: Path) -> list[str]:
    runner = ROOT / "scripts" / "astra_local_historical_gap_runner_v1.py"
    command = [sys.executable, "-B", str(runner), lane, "--state-dir", str(state_dir)]
    if lane == "macro":
        command += ["--max-series", "10", "--max-years", "5"]
    elif lane == "analyst":
        command += ["--symbols", "AAPL", "MSFT", "TSLA", "--max-years", "1"]
    elif lane == "microstructure":
        command += ["--symbols", "AAPL", "MSFT", "TSLA", "--max-days", "5"]
    return command


def _run_child(lane: str, state_dir: Path, log_path: Path, poll_seconds: int) -> dict[str, Any]:
    command = _runner_command(lane, state_dir)
    child = subprocess.Popen(command, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    output: list[str] = []
    blocked = False
    try:
        while child.poll() is None:
            if not resource_gate(state_dir)["allowed"]:
                blocked = True
                child.send_signal(signal.SIGTERM)
                try:
                    child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
                break
            time.sleep(max(1, min(5, poll_seconds)))
        remaining, _ = child.communicate(timeout=10)
        if remaining:
            output.append(remaining[-8192:])
    except Exception as exc:
        child.kill()
        child.wait(timeout=10)
        output.append(f"supervisor child error: {type(exc).__name__}: {exc}")
    _log(log_path, f"lane={lane} child_pid={child.pid} returncode={child.returncode} blocked={blocked} output_tail={''.join(output)[-4096:]!r}")
    if blocked:
        return {"status": "RESOURCE_BLOCKED", "child_pid": child.pid}
    parsed: dict[str, Any] = {}
    for line in reversed("".join(output).splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            parsed = value
            break
    return parsed or {"status": "CHILD_FAILED", "returncode": child.returncode}


def run_once(*, state_dir: Path = STATE_ROOT, pid_path: Path = DEFAULT_PID, status_path: Path = DEFAULT_STATUS, log_path: Path = DEFAULT_LOG, poll_seconds: int = POLL_SECONDS, launch_child: Any = _run_child) -> dict[str, Any]:
    checkpoint_path = _checkpoint_path(state_dir)
    checkpoint = _read_json(checkpoint_path, {"completed_lanes": []})
    completed = set(str(item) for item in checkpoint.get("completed_lanes", []) if item in LANES)
    gate = resource_gate(state_dir)
    if not gate["allowed"]:
        result = {"status": "WAITING_FOR_RESOURCES", "resource_gate": gate, "completed_lanes": sorted(completed), "updated_at": now_iso()}
        _write_json(status_path, result)
        _log(log_path, f"waiting resource_state={gate.get('resource_state')} worker_count={gate.get('worker_count')}")
        return result
    for lane in LANES:
        if lane in completed:
            continue
        if not resource_gate(state_dir)["allowed"]:
            result = {"status": "WAITING_FOR_RESOURCES", "completed_lanes": sorted(completed), "updated_at": now_iso()}
            _write_json(status_path, result)
            return result
        result = launch_child(lane, state_dir, log_path, poll_seconds)
        status = str(result.get("status") or "")
        if status == "RESOURCE_BLOCKED":
            result = {"status": "WAITING_FOR_RESOURCES", "lane": lane, "completed_lanes": sorted(completed), "updated_at": now_iso()}
            _write_json(status_path, result)
            return result
        if status in {"COMPLETE", "NO_SERIES_IDENTIFIED", "UNPROVEN", "PROVEN"}:
            completed.add(lane)
            checkpoint = {"schema_version": "astra_overnight_historical_supervisor_v1", "completed_lanes": sorted(completed), "updated_at": now_iso()}
            _write_json(checkpoint_path, checkpoint)
        else:
            result = {"status": "WAITING_FOR_PROVIDER", "lane": lane, "lane_result": result, "completed_lanes": sorted(completed), "updated_at": now_iso()}
            _write_json(status_path, result)
            return result
    result = {"status": "COMPLETE" if completed == set(LANES) else "WAITING_FOR_PROVIDER", "completed_lanes": sorted(completed), "updated_at": now_iso()}
    _write_json(status_path, result)
    return result


def run_forever(*, state_dir: Path, pid_path: Path, status_path: Path, log_path: Path, poll_seconds: int) -> int:
    if not _claim_pid(pid_path):
        return 0
    try:
        while True:
            result = run_once(state_dir=state_dir, pid_path=pid_path, status_path=status_path, log_path=log_path, poll_seconds=poll_seconds)
            if result.get("status") == "COMPLETE":
                return 0
            time.sleep(max(10, poll_seconds))
    finally:
        _release_pid(pid_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, default=STATE_ROOT)
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID)
    parser.add_argument("--status-file", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--poll-seconds", type=int, default=POLL_SECONDS)
    parser.add_argument("--once", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.once:
        result = run_once(state_dir=args.state_dir, pid_path=args.pid_file, status_path=args.status_file, log_path=args.log_file, poll_seconds=args.poll_seconds)
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    return run_forever(state_dir=args.state_dir, pid_path=args.pid_file, status_path=args.status_file, log_path=args.log_file, poll_seconds=args.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
