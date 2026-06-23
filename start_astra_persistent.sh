#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ROOT_DIR}/state"
LOG_DIR="${ROOT_DIR}/logs"
STARTUP_LOG="${LOG_DIR}/astra_startup.log"

BACKEND_SESSION="${ASTRA_BACKEND_TMUX_SESSION:-astra_backend}"
FRONTEND_SESSION="${ASTRA_FRONTEND_TMUX_SESSION:-astra_frontend}"

BACKEND_PORT="${ASTRA_BACKEND_PORT:-8000}"
FRONTEND_PORT="${ASTRA_FRONTEND_PORT:-5173}"

BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
FRONTEND_HOST="${ASTRA_FRONTEND_HOST:-0.0.0.0}"
START_COMPONENT="${ASTRA_START_COMPONENT:-all}"
SKIP_CLEANUP="${ASTRA_START_SKIP_CLEANUP:-0}"

if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
  FRONTEND_HOST="${ASTRA_FRONTEND_HOST:-0.0.0.0}"
fi

mkdir -p "${STATE_DIR}" "${LOG_DIR}"
exec > >(tee -a "${STARTUP_LOG}") 2>&1

log_info() {
  echo "[start_astra_persistent] $*"
}

is_port_listening() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 1
  fi
  lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
}

wait_for_port() {
  local port="$1"
  local attempts="${2:-20}"
  local delay="${3:-0.5}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if is_port_listening "${port}"; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

wait_for_http_200() {
  local url="$1"
  local attempts="${2:-20}"
  local delay="${3:-0.5}"
  local i code
  for ((i=1; i<=attempts; i++)); do
    code="$(curl -m 3 -sS -o /dev/null -w '%{http_code}' "${url}" 2>/dev/null || echo "000")"
    if [[ "${code}" == "200" ]]; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

wait_for_frontend_html() {
  local url="$1"
  local attempts="${2:-20}"
  local delay="${3:-0.5}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if curl -m 4 -sS "${url}" 2>/dev/null | head -n 1 | grep -qi "<!doctype html"; then
      return 0
    fi
    sleep "${delay}"
  done
  return 1
}

kill_port_listeners() {
  local port="$1"
  if ! command -v lsof >/dev/null 2>&1; then
    return 0
  fi
  local pids
  pids="$(lsof -tiTCP:"${port}" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -n "${pids}" ]]; then
    while IFS= read -r pid; do
      [[ -n "${pid}" ]] || continue
      kill "${pid}" >/dev/null 2>&1 || true
      log_info "killed stale listener pid=${pid} on port ${port}"
    done <<< "${pids}"
  fi
}

stop_tmux_session() {
  local session="$1"
  if tmux has-session -t "${session}" 2>/dev/null; then
    tmux kill-session -t "${session}" >/dev/null 2>&1 || true
    log_info "stopped existing tmux session: ${session}"
  fi
}

if ! command -v tmux >/dev/null 2>&1; then
  log_info "tmux is required but not installed."
  exit 1
fi

if [[ "${START_COMPONENT}" != "all" && "${START_COMPONENT}" != "backend" && "${START_COMPONENT}" != "frontend" ]]; then
  log_info "invalid ASTRA_START_COMPONENT=${START_COMPONENT}; expected all/backend/frontend"
  exit 1
fi

API_BASE_URL="${ASTRA_UI_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"
if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  API_BASE_URL="${ASTRA_UI_API_BASE_URL:-}"
fi

if [[ "${START_COMPONENT}" == "all" && "${SKIP_CLEANUP}" != "1" ]]; then
  # Keep lifecycle consistent and avoid duplicate owners for a full start.
  bash "${ROOT_DIR}/stop_astra_persistent.sh" >/dev/null 2>&1 || true
  log_info "pre-start cleanup invoked via stop_astra_persistent.sh"
  kill_port_listeners "${BACKEND_PORT}"
  kill_port_listeners 5173
  kill_port_listeners 5174
  kill_port_listeners 5175
fi

if [[ "${START_COMPONENT}" == "backend" ]]; then
  stop_tmux_session "${BACKEND_SESSION}"
  kill_port_listeners "${BACKEND_PORT}"
fi
if [[ "${START_COMPONENT}" == "frontend" ]]; then
  stop_tmux_session "${FRONTEND_SESSION}"
  kill_port_listeners "${FRONTEND_PORT}"
fi

if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "backend" ]]; then
  if wait_for_http_200 "http://127.0.0.1:${BACKEND_PORT}/api/health" 2 0.25 && tmux has-session -t "${BACKEND_SESSION}" 2>/dev/null; then
    log_info "backend already healthy in session ${BACKEND_SESSION}; skipping duplicate launch"
  else
    stop_tmux_session "${BACKEND_SESSION}"
    kill_port_listeners "${BACKEND_PORT}"
    tmux new-session -d -s "${BACKEND_SESSION}" \
      "cd '${ROOT_DIR}' && ASTRA_BACKEND_HOST='${BACKEND_HOST}' ASTRA_BACKEND_PORT='${BACKEND_PORT}' ASTRA_REMOTE_MODE='${ASTRA_REMOTE_MODE:-0}' bash '${ROOT_DIR}/start_astra_backend.sh'"
    log_info "backend session launched: ${BACKEND_SESSION} (${BACKEND_HOST}:${BACKEND_PORT})"
  fi
  if wait_for_port "${BACKEND_PORT}" 24 0.5; then
    log_info "backend port ${BACKEND_PORT} is listening"
  else
    log_info "backend failed to bind port ${BACKEND_PORT}; recent backend log:"
    tail -n 80 "${STATE_DIR}/backend.log" 2>/dev/null || true
    exit 1
  fi
  if wait_for_http_200 "http://127.0.0.1:${BACKEND_PORT}/api/health" 24 0.5; then
    log_info "backend /api/health responded with 200"
  else
    log_info "backend /api/health did not reach 200 after startup; recent backend log:"
    tail -n 80 "${STATE_DIR}/backend.log" 2>/dev/null || true
    exit 1
  fi
fi

if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "frontend" ]]; then
  FRONTEND_CMD="cd '${ROOT_DIR}/astra_dashboard/ui' && "
  if [[ -n "${API_BASE_URL}" ]]; then
    FRONTEND_CMD+="VITE_API_BASE_URL='${API_BASE_URL}' "
  fi
  if [[ -n "${ASTRA_REMOTE_ACCESS_TOKEN:-}" ]]; then
    FRONTEND_CMD+="VITE_REMOTE_ACCESS_TOKEN='${ASTRA_REMOTE_ACCESS_TOKEN}' "
  fi
  FRONTEND_CMD+="npm run dev -- --host '${FRONTEND_HOST}' --port '${FRONTEND_PORT}'"

  if wait_for_frontend_html "http://127.0.0.1:${FRONTEND_PORT}" 2 0.25 && tmux has-session -t "${FRONTEND_SESSION}" 2>/dev/null; then
    log_info "frontend already healthy in session ${FRONTEND_SESSION}; skipping duplicate launch"
  else
    stop_tmux_session "${FRONTEND_SESSION}"
    kill_port_listeners "${FRONTEND_PORT}"
    tmux new-session -d -s "${FRONTEND_SESSION}" "${FRONTEND_CMD}"
    log_info "frontend session launched: ${FRONTEND_SESSION} (${FRONTEND_HOST}:${FRONTEND_PORT})"
  fi
  if wait_for_port "${FRONTEND_PORT}" 24 0.5; then
    log_info "frontend port ${FRONTEND_PORT} is listening"
  else
    log_info "frontend failed to bind port ${FRONTEND_PORT}"
    if tmux has-session -t "${FRONTEND_SESSION}" 2>/dev/null; then
      tmux capture-pane -t "${FRONTEND_SESSION}" -p | tail -n 80 || true
    fi
    exit 1
  fi
  if wait_for_frontend_html "http://127.0.0.1:${FRONTEND_PORT}" 24 0.5; then
    log_info "frontend returned HTML"
  else
    log_info "frontend did not return HTML after startup"
    if tmux has-session -t "${FRONTEND_SESSION}" 2>/dev/null; then
      tmux capture-pane -t "${FRONTEND_SESSION}" -p | tail -n 80 || true
    fi
    exit 1
  fi
fi

log_info "started tmux sessions summary:"
if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "backend" ]]; then
  log_info "  - ${BACKEND_SESSION}"
fi
if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "frontend" ]]; then
  log_info "  - ${FRONTEND_SESSION}"
fi
log_info "backend expected: http://127.0.0.1:${BACKEND_PORT}"
log_info "frontend expected: http://127.0.0.1:${FRONTEND_PORT}"
