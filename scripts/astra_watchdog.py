#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path(os.getenv("ASTRA_ROOT", str(Path(__file__).resolve().parents[1]))).resolve()
LOG_DIR = Path(os.getenv("ASTRA_RUNTIME_LOG_DIR", str(ROOT / "logs"))).expanduser()
LOG_PATH = LOG_DIR / "astra_watchdog.log"
RECOVERY_LOG_PATH = LOG_DIR / "astra_recovery.log"
START_SCRIPT = Path(os.getenv("ASTRA_START_SCRIPT", str(ROOT / "scripts" / "start_astra.sh"))).expanduser()
STOP_SCRIPT = ROOT / "scripts" / "stop_astra.sh"
BACKEND_URL = "http://127.0.0.1:8000/api/health"
FRONTEND_URL = "http://127.0.0.1:5173"
STATE_ROOT = Path(os.getenv("ASTRA_STATE_ROOT", str(ROOT / "state"))).expanduser().resolve()
WORKER_STATE_PATH = STATE_ROOT / "astra_worker_runtime_state_v1.json"
RECOVERY_STATE_PATH = STATE_ROOT / "astra_recovery_status_v1.json"


def _state_root_integrity() -> tuple[bool, dict[str, object]]:
    """Require boot code and all relative state users to share one root."""
    boot_state_path = ROOT / "state"
    try:
        boot_state_root = boot_state_path.resolve(strict=True)
    except OSError:
        boot_state_root = boot_state_path.resolve()
    canonical = STATE_ROOT.resolve()
    matches = boot_state_root == canonical
    return matches, {
        "canonical_state_root": str(canonical),
        "boot_state_root": str(boot_state_root),
        "state_root_matches": matches,
    }


def _managed_components() -> set[str]:
    """Return the explicitly supervised components; boot mode omits the UI."""
    raw = os.getenv("ASTRA_WATCHDOG_COMPONENTS", "backend,worker,frontend")
    components = {part.strip().lower() for part in raw.split(",") if part.strip()}
    return components & {"backend", "worker", "frontend"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{_now()} {message}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


def _recovery_log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{_now()} {message}"
    with RECOVERY_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    _log(f"recovery {message}")


def _write_recovery_state(status: str, reason: str, **details: object) -> None:
    """Publish recovery progress without touching broker or trading state."""
    RECOVERY_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": "astra_recovery_status_v1", "status": status, "reason": reason, "updated_at": _now(), **details}
    temporary = RECOVERY_STATE_PATH.with_suffix(".json.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, separators=(",", ":"), sort_keys=True)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, RECOVERY_STATE_PATH)


def _worker_health() -> tuple[bool, bool, dict[str, object]]:
    """Verify the single canonical worker, not a stale runtime snapshot."""
    try:
        state = json.loads(WORKER_STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return False, False, {"reason": "WORKER_STATE_MISSING"}
    pid = int(state.get("active_worker_pid") or state.get("process_id") or 0)
    try:
        result = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "command="], capture_output=True, text=True, timeout=2, check=False)
        command = str(result.stdout or "").strip()
    except (OSError, subprocess.SubprocessError):
        command = ""
    process_ok = bool(state.get("active_worker_present")) and "engine.paper_autopilot_worker" in command
    heartbeat = str(state.get("heartbeat_at") or state.get("updated_at") or "")
    try:
        age = max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(heartbeat.replace("Z", "+00:00"))).total_seconds())
    except ValueError:
        age = None
    heartbeat_ok = age is not None and age <= 180.0
    return process_ok, heartbeat_ok, {"pid": pid or None, "generation": state.get("worker_generation_id"), "heartbeat_age_seconds": round(age, 2) if age is not None else None, "process_ok": process_ok, "heartbeat_ok": heartbeat_ok}


def _http_ok(url: str, *, expect_html: bool = False, timeout: float = 4.0) -> bool:
    try:
        request = Request(url, headers={"User-Agent": "astra-watchdog/1.0"})
        with urlopen(request, timeout=timeout) as response:
            code = int(getattr(response, "status", 0) or 0)
            if code < 200 or code >= 300:
                return False
            if expect_html:
                body = response.read(256).decode("utf-8", "ignore").lower()
                return "<!doctype html" in body or "<html" in body
            return True
    except (OSError, URLError, TimeoutError):
        return False


def _port_listening(port: int) -> bool:
    try:
        result = subprocess.run(
            ["/usr/sbin/lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def _run_script(script: Path, reason: str, *, extra_env: dict[str, str] | None = None) -> int:
    if not script.exists():
        _log(f"script_missing path={script} reason={reason}")
        return 127
    _log(f"script_start path={script} reason={reason}")
    env = os.environ.copy()
    env.setdefault("ASTRA_REMOTE_MODE", "1")
    if extra_env:
        env.update({str(k): str(v) for k, v in extra_env.items()})
    result = subprocess.run(
        ["/bin/bash", str(script)],
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        timeout=90,
        check=False,
    )
    safe_output = "\n".join((result.stdout or "").splitlines()[-20:])
    if safe_output:
        _log(f"script_output path={script.name} code={result.returncode}\n{safe_output}")
    else:
        _log(f"script_output path={script.name} code={result.returncode} no_output")
    return int(result.returncode)


def _recover_component(component: str, reason: str) -> int:
    _recovery_log(f"targeted_recovery_start component={component} reason={reason}")
    code = _run_script(
        START_SCRIPT,
        f"watchdog_targeted_{component}",
        extra_env={
            "ASTRA_START_COMPONENT": component,
            "ASTRA_START_SKIP_CLEANUP": "1",
            "ASTRA_REMOTE_MODE": "1",
        },
    )
    _recovery_log(f"targeted_recovery_done component={component} code={code}")
    return code


def check_once() -> dict[str, object]:
    components = _managed_components()
    backend_port = _port_listening(8000)
    backend_health = _http_ok(BACKEND_URL)
    frontend_port = _port_listening(5173) if "frontend" in components else False
    frontend_health = _http_ok(FRONTEND_URL, expect_html=True) if "frontend" in components else False
    worker_running, worker_heartbeat, worker = _worker_health() if "worker" in components else (False, False, {"reason": "WORKER_NOT_MANAGED"})
    state_root_matches, state_root = _state_root_integrity()
    return {
        "managed_components": sorted(components),
        "backend_running": backend_port,
        "frontend_running": frontend_port,
        "backend_health": backend_health,
        "frontend_health": frontend_health,
        "worker_running": worker_running,
        "worker_heartbeat": worker_heartbeat,
        "worker": worker,
        "state_root": state_root,
        "state_root_matches": state_root_matches,
    }


def ensure_running(*, boot_recovery: bool = False) -> dict[str, object]:
    status = check_once()
    # Older callers/tests may not include the new fact; only an explicit
    # mismatch suppresses recovery.
    if status.get("state_root_matches") is False:
        # A mismatched root could be a stale copied state tree. Refuse recovery
        # rather than stopping a healthy worker owned by the canonical root.
        _write_recovery_state(
            "RECOVERY_FAILED",
            "CANONICAL_STATE_ROOT_MISMATCH",
            state_root=status.get("state_root"),
            worker=status.get("worker"),
        )
        _log("state_root_mismatch recovery_suppressed")
        return status
    components = set(status["managed_components"])
    healthy = bool(
        ("backend" not in components or (status["backend_running"] and status["backend_health"]))
        and ("frontend" not in components or (status["frontend_running"] and status["frontend_health"]))
        and ("worker" not in components or (status["worker_running"] and status["worker_heartbeat"]))
    )
    if healthy:
        _write_recovery_state("RECOVERY_READY", "healthy_runtime", worker=status["worker"], state_root=status.get("state_root"), recovery_actions_used=0)
        _log(
            "healthy backend_running=yes frontend_running=yes "
            "backend_health=ok frontend_health=ok"
        )
        return status
    _write_recovery_state("SYSTEM_BOOT_RECOVERY" if boot_recovery else "BROKER_RECONCILIATION_REQUIRED", "component_liveness_or_health_missing", worker=status["worker"])
    _log(
        "degraded "
        f"backend_running={'yes' if status['backend_running'] else 'no'} "
        f"frontend_running={'yes' if status['frontend_running'] else 'no'} "
        f"backend_health={'ok' if status['backend_health'] else 'fail'} "
        f"frontend_health={'ok' if status['frontend_health'] else 'fail'} "
        f"worker_running={'yes' if status['worker_running'] else 'no'} "
        f"worker_heartbeat={'ok' if status['worker_heartbeat'] else 'stale'}"
    )
    backend_ok = bool(status["backend_running"] and status["backend_health"])
    frontend_ok = bool(status["frontend_running"] and status["frontend_health"])
    if "backend" in components and not backend_ok:
        _write_recovery_state("BACKEND_RECOVERING", "backend_degraded", worker=status["worker"])
        _recover_component("backend", "backend_degraded")
    status = check_once()
    if "worker" in components and not bool(status["worker_running"] and status["worker_heartbeat"]):
        _write_recovery_state("WORKER_RECOVERING", "worker_degraded_or_stale", worker=status["worker"])
        _recover_component("worker", "worker_degraded_or_stale")
    if "frontend" in components and not frontend_ok:
        _recover_component("frontend", "frontend_degraded")
    time.sleep(4)
    recovered = check_once()
    recovered_components = set(recovered["managed_components"])
    final_ok = bool(
        ("backend" not in recovered_components or (recovered["backend_running"] and recovered["backend_health"]))
        and ("frontend" not in recovered_components or (recovered["frontend_running"] and recovered["frontend_health"]))
        and ("worker" not in recovered_components or (recovered["worker_running"] and recovered["worker_heartbeat"]))
    )
    _write_recovery_state("RECOVERY_READY" if final_ok else "RECOVERY_FAILED", "targeted_recovery_complete", worker=recovered["worker"])
    _log(
        "post_recovery "
        f"backend_running={'yes' if recovered['backend_running'] else 'no'} "
        f"frontend_running={'yes' if recovered['frontend_running'] else 'no'} "
        f"backend_health={'ok' if recovered['backend_health'] else 'fail'} "
        f"frontend_health={'ok' if recovered['frontend_health'] else 'fail'} "
        f"worker_running={'yes' if recovered['worker_running'] else 'no'} "
        f"worker_heartbeat={'ok' if recovered['worker_heartbeat'] else 'stale'}"
    )
    return recovered


def run_loop(interval: float) -> int:
    stopped = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True
        _log("watchdog_stop_signal_received")

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    _log("watchdog_started version=1.0.0 mode=operational_reliability_only")
    while not stopped:
        ensure_running()
        slept = 0.0
        while slept < interval and not stopped:
            time.sleep(min(1.0, interval - slept))
            slept += 1.0
    _log("watchdog_exited")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Astra Mac Mini watchdog.")
    parser.add_argument("--loop", action="store_true", help="Run continuously for LaunchAgent use.")
    parser.add_argument("--boot-recovery", action="store_true", help="Mark the first supervised pass as a boot recovery.")
    parser.add_argument("--interval", type=float, default=float(os.getenv("ASTRA_WATCHDOG_INTERVAL_SECONDS", "45")))
    args = parser.parse_args(argv)
    if args.loop:
        _write_recovery_state("SYSTEM_BOOT_RECOVERY" if args.boot_recovery else "BROKER_RECONCILIATION_REQUIRED", "watchdog_started")
        return run_loop(max(10.0, float(args.interval)))
    status = ensure_running(boot_recovery=args.boot_recovery)
    components = set(status.get("managed_components") or [])
    ok = (
        ("backend" not in components or bool(status.get("backend_health")))
        and ("frontend" not in components or bool(status.get("frontend_health")))
        and ("worker" not in components or bool(status.get("worker_running") and status.get("worker_heartbeat")))
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
