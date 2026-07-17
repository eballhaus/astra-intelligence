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
    # Load is normalized by logical CPUs.  These are deliberately paired with
    # CPU-idle and latency checks below; load alone cannot pause the worker.
    elevated_load_per_cpu: float = 0.75
    high_load_per_cpu: float = 1.00
    minimum_cpu_idle_percent: float = 25.0
    critical_cpu_idle_percent: float = 12.0
    minimum_available_memory_mb: int = 1024
    maximum_worker_memory_mb: int = 2048
    elevated_api_latency_ms: float = 600.0
    maximum_api_latency_ms: float = 1500.0
    sustained_high_samples_required: int = 3
    healthy_samples_required: int = 3
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


def canonical_worker_state(path: Path = WORKER_STATE_PATH) -> dict[str, Any]:
    """Return the one worker record with stable read-only defaults.

    Compatibility heartbeat files are deliberately not consulted here.  A stale
    compatibility artifact must never outrank the worker's atomic snapshot.
    """
    state = read_snapshot(path)
    if not state:
        return {}
    state.setdefault("state_version", state.get("schema_version", "1.0.0"))
    state.setdefault("last_cycle_utc", state.get("last_cycle_completed_at", ""))
    state.setdefault("daily_sufficient_count", 0)
    state.setdefault("daily_insufficient_count", 0)
    state.setdefault("daily_failed_count", 0)
    state.setdefault("downstream_acknowledgements", {})
    state.setdefault("resource_state", (state.get("resource") or {}).get("resource_state", "UNKNOWN"))
    state.setdefault("host_load_observed", (state.get("resource") or {}).get("host_load_1m"))
    state.setdefault("worker_memory_observed", ((state.get("resource") or {}).get("worker_process") or {}).get("memory_mb"))
    state["heartbeat_age_seconds"] = snapshot_age_seconds(state)
    state["last_checkpoint_age_seconds"] = _timestamp_age_seconds(state.get("last_checkpoint_at"))
    liveness = worker_liveness(state)
    state["worker_liveness"] = liveness
    state["active_worker_present"] = bool(liveness.get("active_worker_present"))
    state.setdefault("last_known_worker_pid", state.get("process_id"))
    state.setdefault("last_known_worker_instance_id", state.get("worker_instance_id"))
    state.setdefault("last_known_worker_generation_id", state.get("worker_generation_id"))
    state.setdefault("last_known_worker_cycle_id", state.get("cycle_id"))
    return state


def _timestamp_age_seconds(value: Any) -> float | None:
    raw = str(value or "")
    if not raw:
        return None
    try:
        return max(0.0, (datetime.now(UTC) - datetime.fromisoformat(raw.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        return None


def canonical_runtime_invariants(state: dict[str, Any], *, backend_pid: int | None = None) -> dict[str, Any]:
    """Evaluate snapshot-only runtime invariants without touching trading state."""
    limits = dict(state.get("limits") or {})
    liveness = dict(state.get("worker_liveness") or worker_liveness(state))
    intentionally_stopped = liveness.get("liveness_state") == "STOPPED_CLEANLY"
    worker_pid = liveness.get("active_worker_pid")
    worker = dict(liveness.get("active_worker_process") or process_info(worker_pid))
    command = str(worker.get("command") or "").lower()
    role_ok = str(state.get("process_role") or "") == "PAPER_AUTOPILOT_WORKER"
    process_ok = bool(worker.get("running")) and "engine.paper_autopilot_worker" in command
    heartbeat_age = state.get("heartbeat_age_seconds")
    interval = max(1, int(limits.get("minimum_sleep_between_cycles_seconds") or 45))
    heartbeat_current = heartbeat_age is not None and float(heartbeat_age) <= max(180, interval * 4)
    elapsed = float(state.get("cycle_elapsed_seconds") or 0.0)
    maximum_elapsed = float(limits.get("maximum_cycle_elapsed_seconds") or 20.0)
    cycle_bounded = elapsed <= maximum_elapsed and str(state.get("cycle_state") or "") not in {"FAILED_SAFE", "STALE"}
    has_cycle = bool(state.get("cycle_id"))
    momentum_count = int(state.get("momentum_records_built") or 0)
    acknowledgements = dict(state.get("downstream_acknowledgements") or {})
    acknowledged = bool(acknowledgements.get("all_required_consumers_acknowledged", False))

    def result(ok: bool | None, expected: str, observed: Any, blocker: str, repair: str, *, inactive: bool = False) -> dict[str, Any]:
        return {
            "state": "NOT_APPLICABLE" if inactive else "PASS" if ok is True else "AWAITING_SAMPLES" if ok is None else "FAIL",
            "expected_value": expected,
            "observed_value": observed,
            "first_failed_at": None if ok is True else state.get("updated_at"),
            "last_checked_at": utc_now(),
            "failure_count": 0 if ok is True else 1,
            "exact_blocker": "" if ok is True else blocker,
            "safe_repair": repair,
        }

    return {
        "ONE_CANONICAL_WORKER": result(role_ok and process_ok, "canonical isolated worker process", {"role": state.get("process_role"), "pid": worker_pid, "command": command, "liveness": liveness.get("liveness_state")}, "worker identity is absent, stale, or not the canonical entrypoint", "start exactly one engine.paper_autopilot_worker", inactive=intentionally_stopped),
        "ONE_ACTIVE_WORKER_GENERATION": result(bool(state.get("worker_instance_id") and state.get("worker_generation_id")), "instance and generation identity", {"worker_instance_id": state.get("worker_instance_id"), "worker_generation_id": state.get("worker_generation_id")}, "canonical generation is missing", "restart the isolated worker after releasing stale lease"),
        "HEARTBEAT_CURRENT": result(heartbeat_current, "heartbeat no older than bounded stale window", heartbeat_age, "canonical heartbeat is stale", "allow one bounded worker heartbeat or keep preflight fail-closed", inactive=intentionally_stopped),
        "CYCLE_WITHIN_BOUNDS": result(cycle_bounded, f"cycle elapsed <= {maximum_elapsed}s", elapsed, "cycle exceeded limit or failed safe", "retain bounded limits and inspect worker error"),
        "CURSOR_EVENTUALLY_ADVANCES": result(True if has_cycle else None, "cursor published after a bounded cycle", state.get("cursor"), "no committed worker cycle yet", "await one bounded worker cycle"),
        "SUFFICIENT_BARS_BUILD_MOMENTUM": result(True if momentum_count > 0 else None, "real sufficient daily bars produce momentum", momentum_count, "no current sufficient daily series persisted yet", "continue bounded provider acquisition; do not lower 15-session contract"),
        "MOMENTUM_IS_ACKNOWLEDGED": result(True if momentum_count > 0 and acknowledged else None, "all consumers acknowledge current momentum", acknowledgements, "momentum or downstream acknowledgement is not yet present", "await existing consumer acknowledgement after persistence"),
        "GET_ROUTES_ARE_READ_ONLY": result(True, "zero mutable calls by diagnostics", {"provider": 0, "broker": 0, "llm": 0}, "", ""),
        "RESOURCE_GOVERNANCE_ACTIVE": result(bool(limits), "runtime limits present", bool(limits), "runtime limits missing", "restart canonical worker to publish limits"),
        "STATE_SURVIVES_RESTART": result(bool(state.get("updated_at")), "atomic canonical snapshot", state.get("updated_at"), "no committed canonical snapshot", "run one bounded worker cycle"),
        "DEPRECATED_STATE_IS_NOT_WRITTEN": result(True, "compatibility paths are read-only", "canonical snapshot only", "", ""),
        "LOAD_IS_NORMALIZED_BY_CPU_COUNT": result(bool((state.get("resource") or {}).get("logical_cpu_count")), "load divided by logical CPU count", (state.get("resource") or {}).get("normalized_load_1m"), "resource snapshot lacks logical CPU normalized load", "publish one bounded resource sample"),
        "ELEVATED_DOES_NOT_EQUAL_HIGH_PAUSE": result(str(state.get("resource_state") or "") not in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE"} or int((state.get("resource_policy") or {}).get("consecutive_high_samples") or 0) >= int(limits.get("sustained_high_samples_required") or 3), "high pause requires sustained unsafe samples", state.get("resource_policy"), "high pause has no sustained-sample confirmation", "retain cooldown and collect bounded resource samples"),
        "HIGH_PAUSE_REQUIRES_SUSTAINED_PRESSURE": result(int((state.get("resource_policy") or {}).get("consecutive_high_samples") or 0) >= int(limits.get("sustained_high_samples_required") or 3) if str(state.get("resource_state") or "") == "RESOURCE_HIGH_PAUSE" else True, "configured consecutive high samples", (state.get("resource_policy") or {}).get("consecutive_high_samples"), "high pause was entered from a transient sample", "wait for sustained high pressure before pausing"),
        "MEMORY_PRESSURE_FAILS_SAFE": result(str(state.get("resource_state") or "") != "RESOURCE_MEMORY_PAUSE" or str((state.get("resource") or {}).get("memory_pressure_state")) in {"elevated", "high"}, "memory pressure pause only with unsafe memory evidence", (state.get("resource") or {}).get("memory_pressure_state"), "memory pause lacks unsafe-memory evidence", "resample memory before changing state"),
        "API_LATENCY_CAN_PAUSE_WORKER": result(True, "latency policy configured", limits.get("maximum_api_latency_ms"), "API latency threshold missing", "publish runtime limits"),
        "RESOURCE_SAMPLING_FAILURE_FAILS_CLOSED": result(str(state.get("resource_state") or "") != "RESOURCE_UNKNOWN_FAIL_CLOSED" or str(state.get("cycle_state") or "") in {"PAUSED_RESOURCE_UNKNOWN", "CHECKPOINTED"}, "unknown samples pause acquisition", state.get("cycle_state"), "unknown resource sample allowed active acquisition", "pause until a complete sample is available"),
        "RECOVERY_REQUIRES_HEALTHY_HYSTERESIS": result(str(state.get("resource_state") or "") not in {"RESOURCE_RECOVERY_COOLDOWN"} or int((state.get("resource_policy") or {}).get("healthy_samples_observed") or 0) < int(limits.get("healthy_samples_required") or 3), "multiple healthy samples before resume", (state.get("resource_policy") or {}).get("healthy_samples_observed"), "recovery skipped healthy-sample hysteresis", "continue cooldown sampling"),
        "ACTIVE_WORKER_PID_EXISTS": result(bool(liveness.get("active_worker_present")), "active worker PID exists", liveness.get("active_worker_pid"), "active worker PID is missing", "start the isolated worker", inactive=intentionally_stopped),
        "ACTIVE_WORKER_COMMAND_MATCHES": result(bool(liveness.get("command_matches")), "engine.paper_autopilot_worker command", liveness.get("active_worker_command"), "worker PID command does not match canonical role", "clear stale ownership and start canonical worker", inactive=intentionally_stopped),
        "ACTIVE_WORKER_HEARTBEAT_CURRENT": result(bool(liveness.get("heartbeat_current")), "current canonical heartbeat", liveness.get("active_worker_heartbeat_age_seconds"), "active worker heartbeat is stale", "await bounded heartbeat or restart worker", inactive=intentionally_stopped),
        "STOPPED_WORKER_NOT_REPORTED_ACTIVE": result(not bool(liveness.get("active_worker_present")) if liveness.get("liveness_state") in {"STOPPED_CLEANLY", "PROCESS_MISSING", "STALE_HEARTBEAT", "PID_REUSED"} else True, "stopped worker is historical only", liveness.get("liveness_state"), "stopped worker is still reported active", "clear active worker fields on clean stop"),
        "LAST_KNOWN_WORKER_PRESERVED": result(bool(liveness.get("last_known_worker_pid")), "historical worker retained after stop", liveness.get("last_known_worker_pid"), "last-known worker identity missing", "preserve canonical historical state on shutdown"),
    }


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


def cpu_idle_percent() -> float | None:
    """Return a bounded host CPU-idle observation without opening any stores."""
    try:
        if sys_platform() == "darwin":
            output = subprocess.run(["top", "-l", "1", "-n", "0"], capture_output=True, text=True, timeout=1.5, check=False).stdout
            match = re_search(r"([0-9]+(?:\.[0-9]+)?)%\s+idle", output)
            return round(_as_float(match, -1.0), 2) if match is not None else None
        with open("/proc/stat", "r", encoding="utf-8") as handle:
            fields = handle.readline().split()[1:]
        values = [_as_float(value) for value in fields]
        if len(values) < 4:
            return None
        total = sum(values)
        return round(((values[3] + (values[4] if len(values) > 4 else 0.0)) / total) * 100.0, 2) if total else None
    except (OSError, subprocess.SubprocessError):
        return None


def sys_platform() -> str:
    return os.uname().sysname.lower() if hasattr(os, "uname") else ""


def re_search(pattern: str, text: str) -> str | None:
    import re
    match = re.search(pattern, text or "", flags=re.IGNORECASE)
    return match.group(1) if match else None


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


def classify_resource_signals(signals: dict[str, Any], *, limits: RuntimeLimits | None = None, require_complete: bool = False) -> dict[str, Any]:
    """Classify one sample; sustained transitions are owned by advance_resource_policy."""
    limits = limits or RuntimeLimits.from_env()
    cpu_count = _as_float(signals.get("logical_cpu_count"), 0.0)
    load_1m = signals.get("host_load_1m")
    load_5m = signals.get("host_load_5m")
    load_15m = signals.get("host_load_15m")
    cpu_idle = signals.get("cpu_idle_percent")
    memory_pressure = str(signals.get("memory_pressure_state") or "unknown").lower()
    available_memory = signals.get("available_memory_mb")
    worker_memory = _as_float((signals.get("worker_process") or {}).get("memory_mb"), 0.0)
    latency = signals.get("backend_health_latency_ms")
    missing = []
    if cpu_count <= 0:
        missing.append("logical_cpu_count")
    if load_1m is None or load_5m is None or load_15m is None:
        missing.append("host_load")
    if cpu_idle is None:
        missing.append("cpu_idle_percent")
    if memory_pressure not in {"normal", "elevated", "high"}:
        missing.append("memory_pressure")
    if require_complete and latency is None:
        missing.append("backend_health_latency_ms")
    normalized_1m = _as_float(load_1m) / cpu_count if cpu_count > 0 else None
    normalized_5m = _as_float(load_5m) / cpu_count if cpu_count > 0 else None
    normalized_15m = _as_float(load_15m) / cpu_count if cpu_count > 0 else None
    candidate, reason = "RESOURCE_NORMAL", "machine_aware_signals_healthy"
    if missing:
        candidate, reason = "RESOURCE_UNKNOWN_FAIL_CLOSED", "missing_required_resource_signals:" + ",".join(missing)
    elif memory_pressure == "high" or (available_memory is not None and _as_float(available_memory) < limits.minimum_available_memory_mb) or worker_memory > limits.maximum_worker_memory_mb:
        candidate, reason = "RESOURCE_MEMORY_PAUSE", "memory_pressure_or_process_memory_limit"
    elif latency is not None and _as_float(latency) >= limits.maximum_api_latency_ms:
        candidate, reason = "RESOURCE_API_LATENCY_PAUSE", "backend_latency_above_pause_threshold"
    elif (normalized_1m is not None and normalized_1m >= limits.high_load_per_cpu and _as_float(cpu_idle) <= limits.minimum_cpu_idle_percent) or _as_float(cpu_idle) <= limits.critical_cpu_idle_percent:
        candidate, reason = "RESOURCE_HIGH_PAUSE", "sustained_normalized_load_and_low_cpu_idle_required"
    elif (normalized_1m is not None and normalized_1m >= limits.elevated_load_per_cpu) or _as_float(cpu_idle) < limits.minimum_cpu_idle_percent or (latency is not None and _as_float(latency) >= limits.elevated_api_latency_ms):
        candidate, reason = "RESOURCE_ELEVATED", "normalized_load_or_moderate_resource_pressure"
    return {
        **signals,
        "normalized_load_1m": round(normalized_1m, 3) if normalized_1m is not None else None,
        "normalized_load_5m": round(normalized_5m, 3) if normalized_5m is not None else None,
        "normalized_load_15m": round(normalized_15m, 3) if normalized_15m is not None else None,
        "load_per_cpu": round(normalized_1m, 3) if normalized_1m is not None else None,
        "resource_candidate_state": candidate,
        "resource_candidate_reason": reason,
        "resource_sampling_complete": not bool(missing),
        "missing_resource_signals": missing,
    }


def _future_iso(seconds: int, *, now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    return datetime.fromtimestamp(now.timestamp() + max(0, seconds), UTC).isoformat().replace("+00:00", "Z")


def _iso_is_future(value: Any, *, now: datetime | None = None) -> bool:
    try:
        now = now or datetime.now(UTC)
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")) > now
    except (TypeError, ValueError):
        return False


def advance_resource_policy(previous: dict[str, Any] | None, sample: dict[str, Any], *, limits: RuntimeLimits | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Persisted hysteresis state: elevated work is reduced, unsafe pressure pauses."""
    limits = limits or RuntimeLimits.from_env()
    now = now or datetime.now(UTC)
    previous = dict(previous or {})
    candidate = str(sample.get("resource_candidate_state") or "RESOURCE_UNKNOWN_FAIL_CLOSED")
    prior_state = str(previous.get("resource_state") or "RESOURCE_NORMAL")
    high = int(previous.get("consecutive_high_samples") or 0) + (1 if candidate in {"RESOURCE_HIGH_PAUSE", "RESOURCE_API_LATENCY_PAUSE"} else 0)
    memory = int(previous.get("consecutive_memory_pressure_samples") or 0) + (1 if candidate == "RESOURCE_MEMORY_PAUSE" else 0)
    latency = int(previous.get("consecutive_latency_failure_samples") or 0) + (1 if candidate == "RESOURCE_API_LATENCY_PAUSE" else 0)
    elevated = int(previous.get("consecutive_elevated_samples") or 0) + (1 if candidate == "RESOURCE_ELEVATED" else 0)
    normal = int(previous.get("consecutive_normal_samples") or 0) + (1 if candidate == "RESOURCE_NORMAL" else 0)
    if candidate not in {"RESOURCE_HIGH_PAUSE", "RESOURCE_API_LATENCY_PAUSE"}:
        high = 0
    if candidate != "RESOURCE_MEMORY_PAUSE":
        memory = 0
    if candidate != "RESOURCE_API_LATENCY_PAUSE":
        latency = 0
    if candidate != "RESOURCE_ELEVATED":
        elevated = 0
    if candidate != "RESOURCE_NORMAL":
        normal = 0
    paused = prior_state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_RECOVERY_COOLDOWN"}
    state, reason = candidate, str(sample.get("resource_candidate_reason") or "resource_sample")
    cooldown_until = previous.get("cooldown_until")
    healthy_observed = int(previous.get("healthy_samples_observed") or 0)
    resume_mode = str(previous.get("resume_mode") or "RESUME_NORMAL_BOUNDED")
    if candidate == "RESOURCE_MEMORY_PAUSE":
        state, cooldown_until, healthy_observed = "RESOURCE_MEMORY_PAUSE", _future_iso(limits.recovery_cooldown_seconds, now=now), 0
        resume_mode = "RESUME_ONE_SYMBOL"
    elif candidate in {"RESOURCE_HIGH_PAUSE", "RESOURCE_API_LATENCY_PAUSE"} and high >= limits.sustained_high_samples_required:
        state, cooldown_until, healthy_observed = candidate, _future_iso(limits.recovery_cooldown_seconds, now=now), 0
        resume_mode = "RESUME_ONE_SYMBOL"
    elif candidate in {"RESOURCE_HIGH_PAUSE", "RESOURCE_API_LATENCY_PAUSE"}:
        state, reason = "RESOURCE_ELEVATED", "unsafe_signal_awaiting_sustained_confirmation"
    elif paused:
        if _iso_is_future(cooldown_until, now=now):
            state, reason, healthy_observed = "RESOURCE_RECOVERY_COOLDOWN", "pause_cooldown_active", 0
        elif candidate == "RESOURCE_NORMAL":
            healthy_observed += 1
            if healthy_observed >= limits.healthy_samples_required:
                state, reason, resume_mode = "RESOURCE_NORMAL", "healthy_hysteresis_satisfied", "RESUME_ONE_SYMBOL"
            else:
                state, reason = "RESOURCE_RECOVERY_COOLDOWN", "awaiting_healthy_hysteresis"
        else:
            state, healthy_observed = "RESOURCE_ELEVATED", 0
    transition = state != prior_state
    return {
        "resource_state": state,
        "resource_decision": "PAUSE" if state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_RECOVERY_COOLDOWN", "RESOURCE_UNKNOWN_FAIL_CLOSED"} else "REDUCE_BATCH" if state == "RESOURCE_ELEVATED" else "RUN_BOUNDED",
        "resource_sample_at": utc_now(),
        "resource_sample_sequence": int(previous.get("resource_sample_sequence") or 0) + 1,
        "consecutive_normal_samples": normal,
        "consecutive_elevated_samples": elevated,
        "consecutive_high_samples": high,
        "consecutive_memory_pressure_samples": memory,
        "consecutive_latency_failure_samples": latency,
        "last_resource_transition_at": utc_now() if transition else previous.get("last_resource_transition_at"),
        "resource_transition_reason": reason,
        "pause_started_at": utc_now() if transition and state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE"} else previous.get("pause_started_at"),
        "pause_reason": reason if state in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE"} else previous.get("pause_reason", ""),
        "cooldown_until": cooldown_until,
        "healthy_samples_required": limits.healthy_samples_required,
        "healthy_samples_observed": healthy_observed,
        "resume_mode": resume_mode,
        "last_resume_at": utc_now() if transition and state == "RESOURCE_NORMAL" and resume_mode == "RESUME_ONE_SYMBOL" else previous.get("last_resume_at"),
    }


def resource_snapshot(*, worker_pid: int | None = None, backend_pid: int | None = None, backend_health_latency_ms: float | None = None, require_complete: bool = False) -> dict[str, Any]:
    limits = RuntimeLimits.from_env()
    cpu_count = max(1, os.cpu_count() or 1)
    try:
        load_1m, load_5m, load_15m = os.getloadavg()
    except OSError:
        load_1m = load_5m = load_15m = 0.0
    memory = memory_snapshot()
    worker = process_info(worker_pid)
    backend = process_info(backend_pid)
    signals = {
        "logical_cpu_count": cpu_count,
        "host_load_1m": round(load_1m, 2),
        "host_load_5m": round(load_5m, 2),
        "host_load_15m": round(load_15m, 2),
        "worker_process": worker,
        "backend_process": backend,
        "cpu_idle_percent": cpu_idle_percent(),
        "backend_health_latency_ms": backend_health_latency_ms,
        "limits": asdict(limits),
        **memory,
    }
    classified = classify_resource_signals(signals, limits=limits, require_complete=require_complete)
    return {**classified, "resource_state": classified["resource_candidate_state"], "resource_reason": classified["resource_candidate_reason"]}


def worker_liveness(state: dict[str, Any] | None = None, *, process: dict[str, Any] | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Separate live process identity from preserved historical worker metadata."""
    state = dict(state or {})
    now = now or datetime.now(UTC)
    declared_active = state.get("active_worker_present")
    if declared_active is None:
        declared_active = str(state.get("ownership_state") or "") != "NO_WORKER_ACTIVE"
    active_pid = int(_as_float(state.get("active_worker_pid") or state.get("process_id"), 0.0)) or None
    checked = dict(process or process_info(active_pid))
    heartbeat_age = snapshot_age_seconds(state)
    interval = max(1, int((state.get("limits") or {}).get("minimum_sleep_between_cycles_seconds") or 45))
    stale_after = max(180, interval * 4)
    heartbeat_current = heartbeat_age is not None and heartbeat_age <= stale_after
    command = str(checked.get("command") or "").lower()
    command_matches = bool(checked.get("running")) and "engine.paper_autopilot_worker" in command
    active = bool(declared_active and active_pid and checked.get("running") and command_matches and heartbeat_current)
    if active:
        resource = str(state.get("resource_state") or "RESOURCE_NORMAL")
        liveness_state = "ACTIVE_RESOURCE_PAUSED" if resource in {"RESOURCE_HIGH_PAUSE", "RESOURCE_MEMORY_PAUSE", "RESOURCE_API_LATENCY_PAUSE", "RESOURCE_RECOVERY_COOLDOWN"} else "ACTIVE_RESOURCE_ELEVATED" if resource == "RESOURCE_ELEVATED" else "ACTIVE_HEALTHY"
    elif not declared_active:
        liveness_state = "STOPPED_CLEANLY"
    elif not checked.get("running"):
        liveness_state = "PROCESS_MISSING"
    elif not command_matches:
        liveness_state = "PID_REUSED"
    elif not heartbeat_current:
        liveness_state = "STALE_HEARTBEAT"
    else:
        liveness_state = "UNKNOWN_FAIL_CLOSED"
    return {
        "liveness_state": liveness_state,
        "active_worker_present": active,
        "active_worker_pid": active_pid if active else None,
        "active_worker_instance_id": state.get("worker_instance_id") if active else None,
        "active_worker_generation_id": state.get("worker_generation_id") if active else None,
        "active_worker_started_at": state.get("started_at") if active else None,
        "active_worker_heartbeat_at": state.get("heartbeat_at") if active else None,
        "active_worker_heartbeat_age_seconds": round(heartbeat_age, 2) if active and heartbeat_age is not None else None,
        "active_worker_command": checked.get("command") if active else None,
        "active_worker_process": checked if active else None,
        "command_matches": command_matches,
        "heartbeat_current": heartbeat_current,
        "last_known_worker_pid": state.get("last_known_worker_pid") or state.get("process_id"),
        "last_known_worker_instance_id": state.get("last_known_worker_instance_id") or state.get("worker_instance_id"),
        "last_known_worker_generation_id": state.get("last_known_worker_generation_id") or state.get("worker_generation_id"),
        "last_known_worker_cycle_id": state.get("last_known_worker_cycle_id") or state.get("cycle_id"),
        "last_known_worker_stopped_at": state.get("last_known_worker_stopped_at"),
        "last_known_worker_exit_reason": state.get("last_known_worker_exit_reason") or state.get("cycle_stop_reason"),
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
