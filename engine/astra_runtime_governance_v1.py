"""Bounded, process-local runtime governance for Astra services.

This module intentionally owns only runtime metadata.  It never opens broker,
provider, SQLite, JSONL, or learning stores, so API diagnostics can consume its
snapshot without competing with the mutable PaperAutopilot worker.
"""
from __future__ import annotations

import fcntl
import json
import os
import resource
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "state"
WORKER_STATE_PATH = STATE / "astra_worker_runtime_state_v1.json"
WORKER_LOCK_PATH = STATE / "astra_worker_runtime_v1.lock"


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class RuntimeLimits:
    """Conservative host-relative defaults, overridable only by deployment config."""

    maximum_symbols_per_cycle: int = 3
    maximum_provider_requests_per_cycle: int = 12
    maximum_pages_per_symbol: int = 2
    maximum_cycle_elapsed_seconds: int = 20
    maximum_retries_per_symbol_per_cycle: int = 1
    minimum_sleep_between_cycles_seconds: int = 45
    minimum_yield_between_symbols: float = 0.25
    maximum_downstream_symbols_per_cycle: int = 3
    maximum_state_write_duration_seconds: float = 2.0
    high_load_per_cpu: float = 0.85
    elevated_load_per_cpu: float = 0.60
    minimum_available_memory_mb: int = 1024
    log_rotation_bytes: int = 20 * 1024 * 1024
    log_rotation_generations: int = 3
    recovery_cooldown_seconds: int = 120

    @classmethod
    def from_env(cls) -> "RuntimeLimits":
        defaults = cls()
        values: dict[str, Any] = {}
        for name, value in asdict(defaults).items():
            key = "ASTRA_RUNTIME_" + name.upper()
            raw = os.getenv(key)
            if raw is None:
                values[name] = value
            elif isinstance(value, int):
                values[name] = max(0, int(_as_float(raw, value)))
            elif isinstance(value, float):
                values[name] = max(0.0, _as_float(raw, value))
            else:
                values[name] = value
        return cls(**values)


def read_snapshot(path: Path = WORKER_STATE_PATH) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return dict(value) if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, ValueError, TypeError):
        return {}


def write_snapshot(payload: dict[str, Any], path: Path = WORKER_STATE_PATH) -> float:
    """Atomically replace a compact runtime snapshot and return write elapsed time."""
    started = time.monotonic()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = dict(payload)
    data["updated_at"] = utc_now()
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    return time.monotonic() - started


def process_info(pid: int | None) -> dict[str, Any]:
    if not pid or pid <= 0:
        return {"pid": None, "running": False, "command": "", "cpu_percent": 0.0, "memory_mb": 0.0}
    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "pid=,ppid=,%cpu=,rss=,etime=,command="],
            capture_output=True,
            text=True,
            timeout=0.75,
            check=False,
        )
        line = str(result.stdout or "").strip()
        if not line:
            return {"pid": pid, "running": False, "command": "", "cpu_percent": 0.0, "memory_mb": 0.0}
        parts = line.split(None, 5)
        return {
            "pid": int(parts[0]),
            "parent_process_id": int(parts[1]),
            "running": True,
            "cpu_percent": round(_as_float(parts[2]), 0),
            "memory_mb": round(_as_float(parts[3]) / 1024.0, 2),
            "uptime": parts[4] if len(parts) > 4 else "",
            "command": parts[5] if len(parts) > 5 else "",
        }
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"pid": pid, "running": False, "command": "", "cpu_percent": 0.0, "memory_mb": 0.0}


def memory_snapshot() -> dict[str, Any]:
    """Use standard macOS vm_stat when available; never raises in other environments."""
    try:
        output = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=0.75, check=False).stdout
        page_size = 4096
        pages: dict[str, int] = {}
        for line in output.splitlines():
            if "page size of" in line:
                page_size = int(line.split("page size of", 1)[1].split("bytes", 1)[0].strip())
            if ":" in line:
                key, value = line.split(":", 1)
                digits = "".join(ch for ch in value if ch.isdigit())
                if digits:
                    pages[key.strip()] = int(digits)
        available_pages = pages.get("Pages free", 0) + pages.get("Pages inactive", 0) + pages.get("Pages speculative", 0)
        available_mb = available_pages * page_size / (1024 * 1024)
        pressure = "normal" if available_mb >= 2048 else "elevated" if available_mb >= 1024 else "high"
        return {"available_memory_mb": round(available_mb, 1), "memory_pressure_state": pressure}
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return {"available_memory_mb": None, "memory_pressure_state": "unknown"}


def resource_snapshot(*, worker_pid: int | None = None, backend_pid: int | None = None) -> dict[str, Any]:
    limits = RuntimeLimits.from_env()
    cpu_count = max(1, os.cpu_count() or 1)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        load_1m = load_5m = load_15m = 0.0
    memory = memory_snapshot()
    worker = process_info(worker_pid)
    backend = process_info(backend_pid)
    per_cpu_load = load_1m / cpu_count
    state = "RESOURCE_NORMAL"
    reason = "within_conservative_runtime_limits"
    if memory.get("memory_pressure_state") == "high" or (
        memory.get("available_memory_mb") is not None and memory["available_memory_mb"] < limits.minimum_available_memory_mb
    ):
        state, reason = "MEMORY_PRESSURE_PAUSE", "available_memory_below_runtime_floor"
    elif per_cpu_load >= limits.high_load_per_cpu:
        state, reason = "RESOURCE_HIGH_PAUSE", "one_minute_load_above_high_threshold"
    elif per_cpu_load >= limits.elevated_load_per_cpu:
        state, reason = "RESOURCE_ELEVATED", "one_minute_load_above_elevated_threshold"
    return {
        "logical_cpu_count": cpu_count,
        "host_load_1m": round(load_1m, 2),
        "host_load_5m": round(load_5m, 2),
        "host_load_15m": round(load_15m, 2),
        "load_per_cpu": round(per_cpu_load, 3),
        "worker_process": worker,
        "backend_process": backend,
        "resource_state": state,
        "resource_reason": reason,
        "limits": asdict(limits),
        **memory,
    }


def rotate_log(path: str | Path, *, max_bytes: int | None = None, generations: int | None = None) -> dict[str, Any]:
    """Rotate before a process opens the log; no active descriptor is renamed."""
    log_path = Path(path)
    limits = RuntimeLimits.from_env()
    max_bytes = int(max_bytes or limits.log_rotation_bytes)
    generations = int(generations or limits.log_rotation_generations)
    try:
        size = log_path.stat().st_size
    except FileNotFoundError:
        return {"rotated": False, "reason": "missing", "path": str(log_path), "size_bytes": 0}
    if size < max_bytes:
        return {"rotated": False, "reason": "below_limit", "path": str(log_path), "size_bytes": size}
    oldest = log_path.with_name(log_path.name + "." + str(generations))
    oldest.unlink(missing_ok=True)
    for index in range(generations - 1, 0, -1):
        source = log_path.with_name(log_path.name + "." + str(index))
        destination = log_path.with_name(log_path.name + "." + str(index + 1))
        if source.exists():
            os.replace(source, destination)
    os.replace(log_path, log_path.with_name(log_path.name + ".1"))
    log_path.touch()
    return {"rotated": True, "reason": "size_limit", "path": str(log_path), "size_bytes": size, "generations": generations}


class WorkerLease:
    """Single-writer file lock plus generation identity; PID existence is not trusted."""

    def __init__(self, path: Path = WORKER_LOCK_PATH) -> None:
        self.path = path
        self._handle: Any | None = None
        self.instance_id = f"paper-autopilot-{uuid.uuid4().hex[:12]}"
        self.generation_id = f"generation-{os.getpid()}-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    def acquire(self) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._handle.close()
            self._handle = None
            return False
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(json.dumps({"pid": os.getpid(), "worker_instance_id": self.instance_id, "worker_generation_id": self.generation_id, "locked_at": utc_now()}))
        self._handle.flush()
        return True

    def release(self) -> None:
        if self._handle is not None:
            try:
                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            finally:
                self._handle.close()
                self._handle = None


def log_sizes() -> dict[str, int]:
    result: dict[str, int] = {}
    for name in ("backend.log", "worker.log", "paper_worker.log", "watchdog.log", "runtime_health.log"):
        try:
            result[name] = (STATE / name).stat().st_size
        except FileNotFoundError:
            result[name] = 0
    return result


def snapshot_age_seconds(snapshot: dict[str, Any]) -> float | None:
    raw = str(snapshot.get("heartbeat_at") or snapshot.get("updated_at") or "")
    if not raw:
        return None
    try:
        return max(0.0, (datetime.now(UTC) - datetime.fromisoformat(raw.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        return None
