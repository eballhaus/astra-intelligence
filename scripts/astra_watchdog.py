#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

ROOT = Path("/Users/eric/Desktop/astra-intelligence-clean")
LOG_DIR = ROOT / "logs"
LOG_PATH = LOG_DIR / "astra_watchdog.log"
START_SCRIPT = ROOT / "scripts" / "start_astra.sh"
STOP_SCRIPT = ROOT / "scripts" / "stop_astra.sh"
BACKEND_URL = "http://127.0.0.1:8000/api/health"
FRONTEND_URL = "http://127.0.0.1:5173"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"{_now()} {message}"
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    print(line, flush=True)


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


def _run_script(script: Path, reason: str) -> int:
    if not script.exists():
        _log(f"script_missing path={script} reason={reason}")
        return 127
    _log(f"script_start path={script} reason={reason}")
    env = os.environ.copy()
    env.setdefault("ASTRA_REMOTE_MODE", "1")
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


def check_once() -> dict[str, bool]:
    backend_port = _port_listening(8000)
    frontend_port = _port_listening(5173)
    backend_health = _http_ok(BACKEND_URL)
    frontend_health = _http_ok(FRONTEND_URL, expect_html=True)
    return {
        "backend_running": backend_port,
        "frontend_running": frontend_port,
        "backend_health": backend_health,
        "frontend_health": frontend_health,
    }


def ensure_running() -> dict[str, bool]:
    status = check_once()
    if all(status.values()):
        _log(
            "healthy backend_running=yes frontend_running=yes "
            "backend_health=ok frontend_health=ok"
        )
        return status
    _log(
        "degraded "
        f"backend_running={'yes' if status['backend_running'] else 'no'} "
        f"frontend_running={'yes' if status['frontend_running'] else 'no'} "
        f"backend_health={'ok' if status['backend_health'] else 'fail'} "
        f"frontend_health={'ok' if status['frontend_health'] else 'fail'}"
    )
    _run_script(STOP_SCRIPT, "watchdog_recovery_cleanup")
    _run_script(START_SCRIPT, "watchdog_recovery_start")
    time.sleep(4)
    recovered = check_once()
    _log(
        "post_recovery "
        f"backend_running={'yes' if recovered['backend_running'] else 'no'} "
        f"frontend_running={'yes' if recovered['frontend_running'] else 'no'} "
        f"backend_health={'ok' if recovered['backend_health'] else 'fail'} "
        f"frontend_health={'ok' if recovered['frontend_health'] else 'fail'}"
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
    parser.add_argument("--interval", type=float, default=float(os.getenv("ASTRA_WATCHDOG_INTERVAL_SECONDS", "45")))
    args = parser.parse_args(argv)
    if args.loop:
        return run_loop(max(10.0, float(args.interval)))
    status = ensure_running()
    return 0 if all(status.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
