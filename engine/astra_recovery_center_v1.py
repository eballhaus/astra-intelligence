from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import time
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
LOG_DIR = ROOT / "logs"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_bool(value: Any) -> bool:
    return bool(value)


def _run(cmd: list[str], timeout: float = 3.0) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return int(result.returncode), str(result.stdout or "")
    except Exception as exc:
        return 127, f"{type(exc).__name__}: {str(exc)[:180]}"


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=0.6):
            return True
    except OSError:
        return False


def _http_ok(path: str, expected: str | None = None) -> bool:
    code, out = _run(["curl", "-m", "4", "-sS", path], timeout=5.0)
    if code != 0:
        return False
    if expected:
        return expected.lower() in out[:500].lower()
    return bool(out.strip())


def _tmux_has(session: str) -> bool:
    if not shutil.which("tmux"):
        return False
    code, _out = _run(["tmux", "has-session", "-t", session], timeout=2.0)
    return code == 0


def _file_mtime(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except OSError:
        return 0.0


def _latest_mtime(paths: list[Path]) -> tuple[float, str]:
    best_ts = 0.0
    best_path = ""
    for path in paths:
        if path.is_dir():
            try:
                children = sorted(path.glob("*"), key=lambda p: _file_mtime(p), reverse=True)[:20]
            except Exception:
                children = []
            ts, child = _latest_mtime(children)
        else:
            ts, child = _file_mtime(path), str(path)
        if ts > best_ts:
            best_ts, best_path = ts, child
    return best_ts, best_path


def _iso_from_ts(ts: float) -> str:
    if ts <= 0:
        return ""
    return datetime.fromtimestamp(ts, UTC).isoformat().replace("+00:00", "Z")


def _tail(path: Path, lines: int = 80) -> list[str]:
    try:
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8", errors="ignore") as handle:
            return handle.read().splitlines()[-lines:]
    except Exception:
        return []


def _last_recovery_action() -> tuple[str, str, int, str]:
    candidates = [
        LOG_DIR / "astra_recovery.log",
        LOG_DIR / "astra_watchdog.log",
        STATE_DIR / "backend.log",
    ]
    restart_count = 0
    last_action = "none"
    last_time = ""
    last_failure = ""
    for path in candidates:
        for line in _tail(path, 120):
            lower = line.lower()
            if "recovery" in lower or "restart" in lower or "degraded" in lower or "script_start" in lower:
                last_action = line[-260:]
                last_time = line.split(" ", 1)[0] if " " in line else ""
            if "fail" in lower or "degraded" in lower or "error" in lower:
                last_failure = line[-220:]
            if "recovery" in lower or "script_start" in lower or "restart" in lower:
                restart_count += 1
    return last_action, last_time, restart_count, last_failure


def _remote_access() -> dict[str, Any]:
    tailscale_path = shutil.which("tailscale")
    tailscale_status = "not_installed"
    tailscale_ip = ""
    tailscale_online = False
    if tailscale_path:
        code, out = _run([tailscale_path, "status", "--json"], timeout=4.0)
        if code == 0 and out.strip():
            tailscale_status = "reachable"
            tailscale_online = '"Online":true' in out.replace(" ", "")
        else:
            tailscale_status = "installed_status_unavailable"
        code_ip, out_ip = _run([tailscale_path, "ip", "-4"], timeout=3.0)
        if code_ip == 0:
            tailscale_ip = (out_ip.splitlines() or [""])[0].strip()
    return {
        "ssh_port_open": _port_open(22),
        "screen_sharing_port_open": _port_open(5900),
        "tailscale_detected": bool(tailscale_path),
        "tailscale_status": tailscale_status,
        "tailscale_ip": tailscale_ip,
        "tailscale_self_online": tailscale_online,
    }


def _system_status() -> dict[str, Any]:
    boot_time = ""
    code, out = _run(["sysctl", "-n", "kern.boottime"], timeout=2.0)
    if code == 0:
        boot_time = out.strip()[:160]
    try:
        load1, load5, load15 = os.getloadavg()
    except OSError:
        load1 = load5 = load15 = 0.0
    disk = shutil.disk_usage(str(ROOT))
    return {
        "status": "ok",
        "hostname": platform.node(),
        "username": os.getenv("USER") or os.getenv("LOGNAME") or "",
        "uptime": time.time() - psutil_boot_time_fallback(),
        "boot_time": boot_time,
        "current_time": _now_iso(),
        "cpu_load": {"one": round(load1, 3), "five": round(load5, 3), "fifteen": round(load15, 3)},
        "memory_pressure": "not_available_without_psutil",
        "disk_usage": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "used_pct": round((disk.used / disk.total) * 100.0, 2) if disk.total else 0.0,
        },
    }


def psutil_boot_time_fallback() -> float:
    code, out = _run(["sysctl", "-n", "kern.boottime"], timeout=2.0)
    if code == 0:
        import re

        match = re.search(r"sec\s*=\s*(\d+)", out)
        if match:
            return float(match.group(1))
    return time.time()


def _learning_protection() -> dict[str, Any]:
    paths = [
        STATE_DIR / "learning_insights_last_good.json",
        STATE_DIR / "learning_knowledge_graph_v1.jsonl",
        STATE_DIR / "candidate_decision_ledger_v1.jsonl",
        STATE_DIR / "replay_counterfactual_learning_v2.jsonl",
        STATE_DIR / "dashboard_cache",
        STATE_DIR / "backend_watchdog_heartbeat",
    ]
    ts, source = _latest_mtime(paths)
    age_hours = ((time.time() - ts) / 3600.0) if ts > 0 else 999.0
    active = age_hours <= 2.0
    gap = age_hours > 3.0
    return {
        "learning_active": active,
        "last_learning_timestamp": _iso_from_ts(ts),
        "last_learning_source": source,
        "estimated_hours_offline": round(max(0.0, age_hours), 3),
        "learning_gap_detected": gap,
        "catchup_required": gap,
        "catchup_status": "cache_only_catchup_recommended" if gap else "not_required",
        "cache_only_catchup_recommended": gap,
        "manual_review_required": gap,
    }


def _safety_flags() -> dict[str, Any]:
    return {
        "behavior_safe_to_apply": False,
        "broker_execution_added": False,
        "automatic_entries_enabled": False,
        "automatic_exits_enabled": False,
        "automatic_sizing_enabled": False,
        "automatic_allocations_enabled": False,
        "shadow_logic_changed": False,
        "live_trading_changed": False,
        "broker_behavior_changed": False,
        "ranking_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "thresholds_changed": False,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "dashboard_provider_calls_used": 0,
        "dashboard_llm_calls_used": 0,
        "api_calls_used": 0,
    }


class AstraRecoveryCenterV1:
    module_name = "astra_recovery_center_v1"

    def status(self, force: bool = False) -> dict[str, Any]:
        backend_port = _port_open(8000)
        frontend_port = _port_open(5173)
        backend_health = _http_ok("http://127.0.0.1:8000/api/health")
        frontend_health = _http_ok("http://127.0.0.1:5173", "<!doctype html")
        last_action, last_time, restarts_today, last_failure = _last_recovery_action()
        learning = _learning_protection()
        remote = _remote_access()
        services = {
            "backend_running": backend_port,
            "backend_port": 8000,
            "backend_health": backend_health,
            "frontend_running": frontend_port,
            "frontend_port": 5173,
            "frontend_health": frontend_health,
            "tmux_backend_session": _tmux_has("astra_backend"),
            "tmux_frontend_session": _tmux_has("astra_frontend"),
            "workers_detected": (STATE_DIR / "paper_worker_heartbeat.json").exists(),
            "watchdog_running": (STATE_DIR / "backend_watchdog_heartbeat").exists() or _tmux_has("astra_backend"),
        }
        score = 100
        if not backend_health:
            score -= 35
        if not frontend_health:
            score -= 25
        if learning.get("learning_gap_detected"):
            score -= 20
        if not remote.get("tailscale_detected"):
            score -= 5
        score = max(0, min(100, score))
        label = "healthy" if score >= 85 else "warning" if score >= 65 else "degraded" if score >= 35 else "critical"
        return {
            "ok": True,
            "module": self.module_name,
            "status": "ok" if score >= 65 else "degraded",
            "system": _system_status(),
            "astra_services": services,
            "remote_access": remote,
            "learning_protection": learning,
            "recovery": {
                "last_recovery_action": last_action,
                "last_recovery_time": last_time,
                "restart_attempts_today": restarts_today,
                "last_failure_reason": last_failure,
                "logs_available": {
                    "astra_watchdog_log": (LOG_DIR / "astra_watchdog.log").exists(),
                    "astra_recovery_log": (LOG_DIR / "astra_recovery.log").exists(),
                    "astra_startup_log": (LOG_DIR / "astra_startup.log").exists(),
                    "backend_log": (STATE_DIR / "backend.log").exists(),
                },
                "recovery_health_score": score,
                "status_label": label,
            },
            "recovery_health_score": score,
            "status_label": label,
            "generated_at": _now_iso(),
            **_safety_flags(),
        }
