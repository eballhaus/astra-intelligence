#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ROOT_DIR}/state"
VENV_PY="${ROOT_DIR}/venv/bin/python"

WATCHDOG_PID_FILE="${STATE_DIR}/backend_watchdog.pid"
WATCHDOG_HEARTBEAT_FILE="${STATE_DIR}/backend_watchdog_heartbeat"
WATCHDOG_LOG_FILE="${STATE_DIR}/watchdog.log"
UVICORN_PID_FILE="${STATE_DIR}/uvicorn.pid"
PAPER_WORKER_PID_FILE="${STATE_DIR}/paper_worker.pid"
BACKEND_LOG_FILE="${STATE_DIR}/backend.log"
PAPER_WORKER_LOG_FILE="${STATE_DIR}/paper_worker.log"

BACKEND_PORT="${ASTRA_BACKEND_PORT:-8000}"
BACKEND_HOST="${ASTRA_BACKEND_HOST:-127.0.0.1}"
WATCHDOG_SLEEP_SECONDS="${ASTRA_WATCHDOG_SLEEP_SECONDS:-12}"
WATCHDOG_RESTART_COOLDOWN_SECONDS="${ASTRA_WATCHDOG_RESTART_COOLDOWN_SECONDS:-2}"

if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
fi

mkdir -p "${STATE_DIR}"

if [[ -x "${VENV_PY}" ]]; then
  PYTHON_BIN="${VENV_PY}"
else
  PYTHON_BIN="$(command -v python3 || true)"
fi

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "[startup] python not found" >&2
  exit 1
fi

log_watchdog() {
  local now
  now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  echo "[${now}] $*" >> "${WATCHDOG_LOG_FILE}"
}

is_pid_alive() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1
}

read_pid_file() {
  local path="${1:-}"
  [[ -f "${path}" ]] || return 0
  local raw trimmed pid first
  raw="$(cat "${path}" 2>/dev/null || true)"
  trimmed="$(echo "${raw}" | tr -d '[:space:]')"

  if [[ -z "${trimmed}" ]]; then
    return 0
  fi

  if [[ "${trimmed}" =~ ^\{ ]]; then
    pid="$(python3 - <<'PY' "${path}" 2>/dev/null || true
import json,sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    v = obj.get("pid")
    print(int(v) if v is not None else "")
except Exception:
    print("")
PY
)"
    if [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]]; then
      echo "${pid}"
      return 0
    fi
  fi

  first="$(echo "${raw}" | head -n 1 | tr -d '[:space:]')"
  if [[ "${first}" =~ ^[0-9]+$ ]]; then
    echo "${first}"
    return 0
  fi

  pid="$(echo "${raw}" | grep -Eo '[0-9]+' | head -n 1 || true)"
  if [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]]; then
    echo "${pid}"
    return 0
  fi
}

start_uvicorn() {
  local cmd=(
    "${PYTHON_BIN}" -m uvicorn
    server:app
    --host "${BACKEND_HOST}"
    --port "${BACKEND_PORT}"
  )
  (
    cd "${ROOT_DIR}"
    "${cmd[@]}" >> "${BACKEND_LOG_FILE}" 2>&1
  ) &
  local uvicorn_pid="$!"
  echo "${uvicorn_pid}" > "${UVICORN_PID_FILE}"
  log_watchdog "uvicorn started pid=${uvicorn_pid} cmd='${cmd[*]}'"
}

start_paper_worker_if_available() {
  if [[ ! -f "${ROOT_DIR}/engine/paper_worker.py" ]]; then
    return 0
  fi

  local old_pid
  old_pid="$(read_pid_file "${PAPER_WORKER_PID_FILE}")"
  if is_pid_alive "${old_pid}"; then
    log_watchdog "paper_worker pid file detected running pid=${old_pid}; no restart"
    return 0
  fi

  (
    cd "${ROOT_DIR}"
    "${PYTHON_BIN}" -m engine.paper_worker >> "${PAPER_WORKER_LOG_FILE}" 2>&1
  ) &
  local worker_pid="$!"
  echo "${worker_pid}" > "${PAPER_WORKER_PID_FILE}"
  log_watchdog "paper_worker started launcher_pid=${worker_pid}"
}

cleanup_on_exit() {
  local me
  me="$(cat "${WATCHDOG_PID_FILE}" 2>/dev/null || echo "$$")"
  rm -f "${WATCHDOG_PID_FILE}" "${WATCHDOG_HEARTBEAT_FILE}"
  log_watchdog "watchdog exiting pid=${me} (uvicorn left untouched)"
}
trap cleanup_on_exit EXIT

echo "$$" > "${WATCHDOG_PID_FILE}"
log_watchdog "backend watchdog started pid=$$"

while true; do
  date -u +'%Y-%m-%dT%H:%M:%SZ' > "${WATCHDOG_HEARTBEAT_FILE}" || true

  uvicorn_pid="$(read_pid_file "${UVICORN_PID_FILE}")"
  if ! is_pid_alive "${uvicorn_pid}"; then
    if [[ -n "${uvicorn_pid}" ]]; then
      log_watchdog "uvicorn pid=${uvicorn_pid} not alive; restarting"
    else
      log_watchdog "uvicorn missing/dead; restarting"
    fi
    start_uvicorn
    sleep "${WATCHDOG_RESTART_COOLDOWN_SECONDS}"
  fi

  start_paper_worker_if_available
  sleep "${WATCHDOG_SLEEP_SECONDS}"
done
