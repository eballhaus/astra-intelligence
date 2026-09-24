"""Bounded background-work scheduling under the existing resource authority.

This module is deliberately a pure planner.  It does not start processes,
change trading state, or override the worker resource policy.  Existing
supervisors use its plan to decide whether their already-owned bounded unit
may run.
"""
from __future__ import annotations

import os
import json
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - macOS/Linux provide fcntl
    fcntl = None


VERSION = "astra_resource_aware_workload_scheduler_v1"
SCALE_UP_HEALTHY_SAMPLES = 3
SCALE_UP_COOLDOWN_SAMPLES = 2
MAX_BACKGROUND_WORKERS = 3
PAUSED_STATES = {
    "RESOURCE_HIGH_PAUSE",
    "RESOURCE_MEMORY_PAUSE",
    "RESOURCE_API_LATENCY_PAUSE",
    "RESOURCE_UNKNOWN_FAIL_CLOSED",
}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _resource_facts(state: Mapping[str, Any]) -> dict[str, Any]:
    resource = state.get("resource") if isinstance(state.get("resource"), Mapping) else state
    telemetry = resource.get("resource_memory_telemetry_v1") if isinstance(resource, Mapping) else {}
    process = resource.get("worker_process") if isinstance(resource, Mapping) else {}
    telemetry = telemetry if isinstance(telemetry, Mapping) else {}
    process = process if isinstance(process, Mapping) else {}
    timing = state.get("cycle_timing_v1") if isinstance(state.get("cycle_timing_v1"), Mapping) else {}
    latest = timing.get("latest") if isinstance(timing.get("latest"), Mapping) else {}
    return {
        "resource_state": str(resource.get("resource_state") or state.get("resource_state") or "RESOURCE_UNKNOWN_FAIL_CLOSED").upper(),
        "rss_mb": _float(process.get("memory_mb") or telemetry.get("current_rss_mb")),
        "rss_slope_mb_per_hour": _float(telemetry.get("rss_growth_mb_per_hour")),
        "cpu_percent": _float(process.get("cpu_percent")),
        "system_cpu_percent": _float(resource.get("system_cpu_percent") or state.get("system_cpu_percent")),
        "cycle_seconds": _float(latest.get("total_seconds") or timing.get("total_seconds")),
        "background_suspended": bool(telemetry.get("background_work_suspended") or state.get("background_work_suspended")),
        "last_error": str(state.get("last_error") or state.get("worker_cycle_error") or ""),
        "market_mode": str(state.get("market_hours_mode") or state.get("market_state") or "NORMAL_MARKET").upper(),
        "active_positions": _int(state.get("active_position_count") or state.get("open_position_count")),
        "queue_depth": _int(state.get("background_queue_depth")),
    }


def _market_mode(value: str) -> str:
    value = value.upper()
    if any(token in value for token in ("OVERNIGHT", "IDLE", "CLOSED")):
        return "OVERNIGHT_IDLE"
    if any(token in value for token in ("AFTER", "POST_MARKET")):
        return "AFTER_HOURS"
    if any(token in value for token in ("OPEN", "REGULAR", "MARKET")):
        return "NORMAL_MARKET"
    return "NORMAL_MARKET"


def _current_market_mode() -> str:
    """Use local session time only when the worker has not published a mode."""
    try:
        from zoneinfo import ZoneInfo

        local = datetime.now(ZoneInfo("America/New_York"))
        if local.weekday() >= 5:
            return "OVERNIGHT_IDLE"
        minutes = local.hour * 60 + local.minute
        if 9 * 60 + 30 <= minutes < 16 * 60:
            return "NORMAL_MARKET"
        if minutes >= 16 * 60:
            return "AFTER_HOURS"
        return "NORMAL_MARKET"
    except Exception:
        return "NORMAL_MARKET"


def _host_limit(cpu_count: int | None = None) -> int:
    logical = max(1, int(cpu_count or os.cpu_count() or 1))
    # Keep at least two logical CPUs for the foreground worker and the OS.
    return max(1, min(MAX_BACKGROUND_WORKERS, logical - 2))


def build_resource_aware_workload_plan(
    state: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    cpu_count: int | None = None,
) -> dict[str, Any]:
    """Return a bounded concurrency plan without taking control authority.

    Pressure scales down immediately.  Scale-up requires three consecutive
    healthy samples and never exceeds the host-derived cap.  Provider-backed
    acquisition and canonical learning remain single-owner workloads; the
    worker count is a ceiling for independently owned background processes,
    not permission to clone either owner.
    """
    facts = _resource_facts(state)
    previous = dict(previous or {})
    resource_state = facts["resource_state"]
    market_mode = _market_mode(facts["market_mode"] if facts["market_mode"] != "NORMAL_MARKET" else _current_market_mode())
    pressure = (
        resource_state in PAUSED_STATES
        or facts["background_suspended"]
        or bool(facts["last_error"])
        or facts["cpu_percent"] >= 90.0
        or facts["system_cpu_percent"] >= 90.0
        or facts["cycle_seconds"] >= 30.0
        or facts["rss_slope_mb_per_hour"] >= 180.0
    )
    healthy = not pressure and resource_state == "RESOURCE_NORMAL"
    healthy_samples = _int(previous.get("healthy_samples")) + 1 if healthy else 0
    cooldown_samples = _int(previous.get("cooldown_samples")) + 1 if not healthy else 0
    host_limit = _host_limit(cpu_count)

    if resource_state in PAUSED_STATES or facts["background_suspended"] or facts["last_error"]:
        mode = "TRADING_BUSY"
        max_workers = 0
        ceiling = "NONE"
        reason = "RESOURCE_OR_HEALTH_PAUSE"
    elif resource_state == "RESOURCE_ELEVATED" or pressure:
        mode = "TRADING_BUSY"
        max_workers = 1
        ceiling = "ACQUISITION_ONLY"
        reason = "FOREGROUND_PRESSURE_REDUCE_BACKGROUND"
    else:
        requested = 1 if market_mode == "NORMAL_MARKET" else host_limit
        prior_max = _int(previous.get("max_background_workers"), 1)
        if healthy_samples >= SCALE_UP_HEALTHY_SAMPLES:
            max_workers = min(host_limit, max(1, requested))
        elif prior_max > 1 and cooldown_samples < SCALE_UP_COOLDOWN_SAMPLES:
            max_workers = min(host_limit, prior_max)
        else:
            max_workers = 1
        mode = market_mode
        ceiling = "BACKGROUND_BOUNDED"
        reason = "SUSTAINED_RESOURCE_HEADROOM" if max_workers > 1 else "CONSERVATIVE_FOREGROUND_RESERVE"

    return {
        "schema_version": VERSION,
        "authority": "EXISTING_RESOURCE_GOVERNOR_AND_SENTINEL",
        "mode": mode,
        "resource_state": resource_state,
        "max_background_workers": max_workers,
        "host_worker_cap": host_limit,
        "active_background_workers": min(_int(state.get("active_background_workers")), max_workers),
        "background_priority_ceiling": ceiling,
        "healthy_samples": min(healthy_samples, SCALE_UP_HEALTHY_SAMPLES),
        "cooldown_samples": min(cooldown_samples, SCALE_UP_COOLDOWN_SAMPLES),
        "scale_up_after_healthy_samples": SCALE_UP_HEALTHY_SAMPLES,
        "scale_down_immediate": True,
        "reason": reason,
        "workload_limits": {
            "HISTORICAL_ACQUISITION": 1 if max_workers else 0,
            "HISTORICAL_LEARNING": 1 if max_workers else 0,
            "COMPRESSION_ARCHIVE": max(0, max_workers - 1),
            "READ_ONLY_DIAGNOSTICS": 0,
        },
        "ownership": {
            "trading_worker": "SINGLE_CANONICAL_OWNER",
            "historical_acquisition": "EXISTING_SUPERVISOR_SINGLE_OWNER",
            "historical_learning": "EXISTING_SUPERVISOR_SINGLE_OWNER",
            "broker_lifecycle_truth": "TRADING_WORKER_ONLY",
        },
        "paper_only_preserved": True,
        "trading_authority_changed": False,
    }


def scheduler_plan_from_state_dir(state_dir: Path) -> dict[str, Any] | None:
    """Read the existing worker state for external supervisor coordination."""
    path = Path(state_dir) / "astra_worker_runtime_state_v1.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return build_resource_aware_workload_plan(value)


def _lease_paths(state_dir: Path) -> tuple[Path, Path]:
    root = Path(state_dir)
    return root / f"{VERSION}.json", root / f"{VERSION}.lock"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def claim_background_slot(state_dir: Path, owner: str, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Claim one short-lived scheduler lease for an existing supervisor unit."""
    state_path, lock_path = _lease_paths(Path(state_dir))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    plan = dict(plan or scheduler_plan_from_state_dir(Path(state_dir)) or {})
    maximum = max(0, _int(plan.get("max_background_workers")))
    if maximum <= 0:
        return {"acquired": False, "status": "RESOURCE_BLOCKED", "reason": plan.get("reason") or "NO_BACKGROUND_CAPACITY"}
    with lock_path.open("a+", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                payload = {}
            leases = [
                dict(item) for item in list(payload.get("leases") or [])
                if isinstance(item, Mapping) and (_pid_alive(_int(item.get("pid"))) or _int(item.get("pid")) == os.getpid())
            ]
            if any(str(item.get("owner")) == owner and _int(item.get("pid")) == os.getpid() for item in leases):
                return {"acquired": True, "status": "ALREADY_HELD", "owner": owner, "active": len(leases), "maximum": maximum}
            if len(leases) >= maximum:
                payload.update({"schema_version": VERSION, "leases": leases, "maximum": maximum, "updated_at": time.time(), "status": "WAITING_FOR_SLOT"})
                state_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
                return {"acquired": False, "status": "WAITING_FOR_SLOT", "active": len(leases), "maximum": maximum}
            leases.append({"owner": owner, "pid": os.getpid(), "acquired_at": time.time()})
            payload.update({"schema_version": VERSION, "leases": leases, "maximum": maximum, "updated_at": time.time(), "status": "ACTIVE"})
            state_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
            return {"acquired": True, "status": "ACQUIRED", "owner": owner, "active": len(leases), "maximum": maximum}
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def release_background_slot(state_dir: Path, owner: str) -> None:
    state_path, lock_path = _lease_paths(Path(state_dir))
    if not state_path.exists():
        return
    with lock_path.open("a+", encoding="utf-8") as lock:
        if fcntl is not None:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                payload = json.loads(state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError, TypeError):
                return
            leases = [
                dict(item) for item in list(payload.get("leases") or [])
                if isinstance(item, Mapping) and not (str(item.get("owner")) == owner and _int(item.get("pid")) == os.getpid())
            ]
            payload.update({"leases": leases, "updated_at": time.time(), "status": "ACTIVE" if leases else "IDLE"})
            state_path.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        finally:
            if fcntl is not None:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


@contextmanager
def background_slot(state_dir: Path, owner: str, plan: Mapping[str, Any] | None = None):
    lease = claim_background_slot(state_dir, owner, plan)
    if not lease.get("acquired"):
        yield lease
        return
    try:
        yield lease
    finally:
        release_background_slot(state_dir, owner)
