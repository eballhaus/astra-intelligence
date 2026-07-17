#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ROOT_DIR}/state"
VENV_PY="${ROOT_DIR}/venv/bin/python"

WATCHDOG_PID_FILE="${STATE_DIR}/backend_watchdog.pid"
WATCHDOG_HEARTBEAT_FILE="${STATE_DIR}/backend_watchdog_heartbeat"
WATCHDOG_LOG_FILE="${STATE_DIR}/watchdog.log"
RUNTIME_HEALTH_LOG_FILE="${STATE_DIR}/runtime_health.log"
UVICORN_PID_FILE="${STATE_DIR}/uvicorn.pid"
BACKEND_LOG_FILE="${STATE_DIR}/backend.log"

BACKEND_PORT="${ASTRA_BACKEND_PORT:-8000}"
BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
WATCHDOG_SLEEP_SECONDS="${ASTRA_WATCHDOG_SLEEP_SECONDS:-12}"
WATCHDOG_RESTART_COOLDOWN_SECONDS="${ASTRA_WATCHDOG_RESTART_COOLDOWN_SECONDS:-2}"

if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
fi

mkdir -p "${STATE_DIR}"

rotate_log_before_open() {
  local path="$1" limit="${ASTRA_RUNTIME_LOG_ROTATION_BYTES:-20971520}" keep="${ASTRA_RUNTIME_LOG_ROTATION_GENERATIONS:-3}"
  [[ -f "${path}" ]] || return 0
  local size
  size="$(stat -f%z "${path}" 2>/dev/null || echo 0)"
  [[ "${size}" =~ ^[0-9]+$ ]] || return 0
  [[ "${size}" -ge "${limit}" ]] || return 0
  local i
  for ((i=keep; i>=1; i--)); do
    if [[ "${i}" -eq "${keep}" ]]; then rm -f "${path}.${i}"; fi
    if [[ -f "${path}.$((i - 1))" ]]; then mv "${path}.$((i - 1))" "${path}.${i}"; fi
  done
  mv "${path}" "${path}.1"
  : > "${path}"
}

# This script is invoked only before the API process opens its descriptors.
rotate_log_before_open "${BACKEND_LOG_FILE}"
rotate_log_before_open "${WATCHDOG_LOG_FILE}"
rotate_log_before_open "${RUNTIME_HEALTH_LOG_FILE}"

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

log_runtime_health() {
  local now backend_pid backend_alive frontend_alive
  now="$(date -u +'%Y-%m-%dT%H:%M:%SZ')"
  backend_pid="$(read_pid_file "${UVICORN_PID_FILE}")"
  if is_pid_alive "${backend_pid}"; then backend_alive="up"; else backend_alive="down"; fi
  if lsof -nP -iTCP:5173 -sTCP:LISTEN >/dev/null 2>&1; then frontend_alive="up"; else frontend_alive="down"; fi
  echo "${now} backend=${backend_alive} backend_pid=${backend_pid:-none} frontend=${frontend_alive} worker=externally_supervised" >> "${RUNTIME_HEALTH_LOG_FILE}"
}

is_pid_alive() {
  local pid="${1:-}"
  [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]] && kill -0 "${pid}" >/dev/null 2>&1
}

backend_listener_pid() {
  local pid=""
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  pid="$(lsof -tiTCP:"${BACKEND_PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]]; then
    echo "${pid}"
  fi
}

wait_for_backend_listener_pid() {
  local attempts="${1:-20}"
  local delay="${2:-0.15}"
  local i pid
  for ((i=1; i<=attempts; i++)); do
    pid="$(backend_listener_pid)"
    if [[ -n "${pid}" ]] && [[ "${pid}" =~ ^[0-9]+$ ]]; then
      echo "${pid}"
      return 0
    fi
    sleep "${delay}"
  done
  return 1
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
  return 0
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
    ASTRA_PROCESS_ROLE=api "${cmd[@]}" >> "${BACKEND_LOG_FILE}" 2>&1
  ) &
  local launcher_pid="$!"
  echo "${launcher_pid}" > "${UVICORN_PID_FILE}"

  local listener_pid=""
  if command -v lsof >/dev/null 2>&1; then
    listener_pid="$(wait_for_backend_listener_pid 20 0.15 || true)"
  fi

  if [[ -n "${listener_pid}" ]] && [[ "${listener_pid}" =~ ^[0-9]+$ ]]; then
    echo "${listener_pid}" > "${UVICORN_PID_FILE}"
    log_watchdog "uvicorn started launcher_pid=${launcher_pid} listener_pid=${listener_pid} cmd='${cmd[*]}'"
  else
    log_watchdog "uvicorn started launcher_pid=${launcher_pid} listener_pid=unresolved cmd='${cmd[*]}'"
  fi
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
    listener_pid="$(backend_listener_pid)"
    if is_pid_alive "${listener_pid}"; then
      echo "${listener_pid}" > "${UVICORN_PID_FILE}"
      log_watchdog "uvicorn pid file stale (${uvicorn_pid:-none}); listener pid=${listener_pid} adopted"
      uvicorn_pid="${listener_pid}"
    fi
  fi
  if ! is_pid_alive "${uvicorn_pid}"; then
    if [[ -n "${uvicorn_pid}" ]]; then
      log_watchdog "uvicorn pid=${uvicorn_pid} not alive; restarting"
    else
      log_watchdog "uvicorn missing/dead; restarting"
    fi
    start_uvicorn
    sleep "${WATCHDOG_RESTART_COOLDOWN_SECONDS}"
  fi

  log_runtime_health
  sleep "${WATCHDOG_SLEEP_SECONDS}"
done
