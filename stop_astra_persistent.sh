#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ROOT_DIR}/state"

BACKEND_SESSION="${ASTRA_BACKEND_TMUX_SESSION:-astra_backend}"
WORKER_SESSION="${ASTRA_WORKER_TMUX_SESSION:-astra_worker}"
FRONTEND_SESSION="${ASTRA_FRONTEND_TMUX_SESSION:-astra_frontend}"

WATCHDOG_PID_FILE="${STATE_DIR}/backend_watchdog.pid"
UVICORN_PID_FILE="${STATE_DIR}/uvicorn.pid"
PAPER_WORKER_PID_FILE="${STATE_DIR}/paper_worker.pid"
WATCHDOG_HEARTBEAT_FILE="${STATE_DIR}/backend_watchdog_heartbeat"

log_info() {
  echo "[stop_astra_persistent] $*"
}

log_info_err() {
  echo "[stop_astra_persistent] $*" >&2
}

safe_kill_pid() {
  local pid="${1:-}"
  if [[ -z "${pid}" ]]; then
    log_info "skip kill: empty pid"
    return 0
  fi
  if [[ ! "${pid}" =~ ^[0-9]+$ ]]; then
    log_info "skip kill: non-numeric pid='${pid}'"
    return 0
  fi
  local command
  command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  if [[ "${command}" != *"uvicorn server:app"* && "${command}" != *"engine.paper_autopilot_worker"* && "${command}" != *"backend_watchdog"* && "${command}" != *"start_astra_backend.sh"* && "${command}" != *"npm run dev"* && "${command}" != *"vite"* ]]; then
    log_info "skip kill: pid=${pid} is not a recognized Astra runtime process"
    return 0
  fi
  kill "${pid}" >/dev/null 2>&1 || true
  log_info "kill attempted for pid=${pid}"
}

read_pid() {
  local path="${1:-}"
  [[ -f "${path}" ]] || {
    log_info_err "pid file missing: ${path}"
    return 0
  }

  local raw first trimmed pid=""
  raw="$(cat "${path}" 2>/dev/null || true)"
  trimmed="$(echo "${raw}" | tr -d '[:space:]')"

  if [[ -z "${trimmed}" ]]; then
    log_info_err "pid file empty: ${path}"
    return 0
  fi

  if [[ "${trimmed}" =~ ^\{ ]]; then
    # JSON format, expected e.g. {"pid":1234,...}
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
    if [[ -n "${pid}" ]]; then
      log_info_err "pid parsed (json): ${path} -> ${pid}"
      echo "${pid}"
      return 0
    fi
    log_info_err "pid json parse failed: ${path}"
  fi

  # Plaintext fallback: first line if numeric, otherwise first numeric token.
  first="$(echo "${raw}" | head -n 1 | tr -d '[:space:]')"
  if [[ "${first}" =~ ^[0-9]+$ ]]; then
    log_info_err "pid parsed (plain): ${path} -> ${first}"
    echo "${first}"
    return 0
  fi

  pid="$(echo "${raw}" | grep -Eo '[0-9]+' | head -n 1 || true)"
  if [[ -n "${pid}" ]]; then
    log_info_err "pid parsed (fallback token): ${path} -> ${pid}"
    echo "${pid}"
    return 0
  fi

  log_info_err "pid parse failed: ${path}"
}

if command -v tmux >/dev/null 2>&1; then
  # Stop mutable worker first, allowing its signal handler to checkpoint its
  # compact state before API/frontend supervision is stopped.
  if tmux has-session -t "${WORKER_SESSION}" 2>/dev/null; then
    tmux kill-session -t "${WORKER_SESSION}" || true
    log_info "tmux session killed: ${WORKER_SESSION}"
  else
    log_info "tmux session missing: ${WORKER_SESSION}"
  fi
  if tmux has-session -t "${FRONTEND_SESSION}" 2>/dev/null; then
    tmux kill-session -t "${FRONTEND_SESSION}" || true
    log_info "tmux session killed: ${FRONTEND_SESSION}"
  else
    log_info "tmux session missing: ${FRONTEND_SESSION}"
  fi
  if tmux has-session -t "${BACKEND_SESSION}" 2>/dev/null; then
    tmux kill-session -t "${BACKEND_SESSION}" || true
    log_info "tmux session killed: ${BACKEND_SESSION}"
  else
    log_info "tmux session missing: ${BACKEND_SESSION}"
  fi
fi

safe_kill_pid "$(read_pid "${WATCHDOG_PID_FILE}")"
safe_kill_pid "$(read_pid "${UVICORN_PID_FILE}")"
safe_kill_pid "$(read_pid "${PAPER_WORKER_PID_FILE}")"

# Conservative fallback: target only canonical Astra runtime patterns.
pkill -f "uvicorn server:app --host .* --port 8000" >/dev/null 2>&1 || true
pkill -f "engine.paper_autopilot_worker" >/dev/null 2>&1 || true
pkill -f "npm run dev -- --host .* --port 5173" >/dev/null 2>&1 || true
if command -v lsof >/dev/null 2>&1; then
  for port in 5173 5174 5175 8000; do
    for pid in $(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true); do
      safe_kill_pid "${pid}"
    done
  done
fi
log_info "fallback pkill patterns applied (non-fatal)"

rm -f "${WATCHDOG_PID_FILE}" "${UVICORN_PID_FILE}" "${PAPER_WORKER_PID_FILE}" "${WATCHDOG_HEARTBEAT_FILE}"

log_info "removed canonical pid/heartbeat files"
log_info "stopped canonical Astra tmux sessions/processes."
