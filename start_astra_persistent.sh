#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load Astra's canonical persistent configuration for every startup path.
# Exported values are inherited by the backend, worker, and frontend.
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi
STATE_DIR="${ROOT_DIR}/state"
LOG_DIR="${ROOT_DIR}/logs"
STARTUP_LOG="${LOG_DIR}/astra_startup.log"

BACKEND_SESSION="${ASTRA_BACKEND_TMUX_SESSION:-astra_backend}"
WORKER_SESSION="${ASTRA_WORKER_TMUX_SESSION:-astra_worker}"
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

rotate_frontend_log() {
  local path="${STATE_DIR}/frontend.log" limit="${ASTRA_RUNTIME_LOG_ROTATION_BYTES:-20971520}"
  [[ -f "${path}" ]] || return 0
  local size
  size="$(stat -f%z "${path}" 2>/dev/null || echo 0)"
  [[ "${size}" =~ ^[0-9]+$ && "${size}" -ge "${limit}" ]] || return 0
  rm -f "${path}.3"
  [[ -f "${path}.2" ]] && mv "${path}.2" "${path}.3"
  [[ -f "${path}.1" ]] && mv "${path}.1" "${path}.2"
  mv "${path}" "${path}.1"
  : > "${path}"
}

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

wait_for_port_release() {
  local port="$1"
  local attempts="${2:-30}"
  local delay="${3:-0.5}"
  local i
  for ((i=1; i<=attempts; i++)); do
    if ! is_port_listening "${port}"; then
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

is_astra_listener() {
  local port="$1"
  local pid="$2"
  local command
  command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  if [[ "${port}" == "8000" ]]; then
    [[ "${command}" == *"uvicorn server:app"* || "${command}" == *"start_astra_backend.sh"* || "${command}" == *"backend_watchdog"* ]]
  else
    [[ "${command}" == *"npm run dev"* || "${command}" == *"vite"* ]]
  fi
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
      if ! is_astra_listener "${port}" "${pid}"; then
        log_info "unexpected listener pid=${pid} on port ${port}; refusing to kill it"
        return 1
      fi
      kill "${pid}" >/dev/null 2>&1 || true
      log_info "stopped Astra listener pid=${pid} on port ${port}"
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

stop_canonical_worker() {
  local snapshot="${STATE_DIR}/astra_worker_runtime_state_v1.json"
  local pid command attempt
  [[ -f "${snapshot}" ]] || return 0
  pid="$(python3 - "${snapshot}" <<'PY' 2>/dev/null || true
import json, sys
try:
    with open(sys.argv[1], "r", encoding="utf-8") as handle:
        state = json.load(handle)
    if state.get("active_worker_present") is False:
        raise SystemExit
    value = state.get("active_worker_pid") or state.get("process_id")
    print(int(value) if value else "")
except Exception:
    pass
PY
)"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 0
  command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  if [[ "${command}" != *"engine.paper_autopilot_worker"* ]]; then
    return 0
  fi
  kill -TERM "${pid}" >/dev/null 2>&1 || true
  for attempt in {1..20}; do
    if ! ps -p "${pid}" >/dev/null 2>&1; then
      log_info "canonical worker checkpointed: ${pid}"
      return 0
    fi
    sleep 0.25
  done
  log_info "canonical worker did not exit after bounded TERM wait: ${pid}"
}

if ! command -v tmux >/dev/null 2>&1; then
  log_info "tmux is required but not installed."
  exit 1
fi

if [[ "${START_COMPONENT}" != "all" && "${START_COMPONENT}" != "backend" && "${START_COMPONENT}" != "worker" && "${START_COMPONENT}" != "frontend" ]]; then
  log_info "invalid ASTRA_START_COMPONENT=${START_COMPONENT}; expected all/backend/worker/frontend"
  exit 1
fi

VITE_PROXY_TARGET="${ASTRA_VITE_API_TARGET:-http://127.0.0.1:${BACKEND_PORT}}"
VITE_ALLOWED_HOSTS="${ASTRA_VITE_ALLOWED_HOSTS:-${VITE_ALLOWED_HOSTS:-}}"

if [[ "${START_COMPONENT}" == "all" && "${SKIP_CLEANUP}" != "1" ]]; then
  # Keep lifecycle consistent and avoid duplicate owners for a full start.
  bash "${ROOT_DIR}/stop_astra_persistent.sh" >/dev/null 2>&1 || true
  log_info "pre-start cleanup invoked via stop_astra_persistent.sh"
  if ! wait_for_port_release "${BACKEND_PORT}" 30 0.5; then
    log_info "backend port ${BACKEND_PORT} did not release after stop"
    exit 1
  fi
  kill_port_listeners "${BACKEND_PORT}"
  kill_port_listeners 5173
  kill_port_listeners 5174
  kill_port_listeners 5175
fi

if [[ "${START_COMPONENT}" == "backend" ]]; then
  stop_tmux_session "${BACKEND_SESSION}"
  kill_port_listeners "${BACKEND_PORT}"
  wait_for_port_release "${BACKEND_PORT}" 30 0.5
fi
if [[ "${START_COMPONENT}" == "worker" ]]; then
  stop_tmux_session "${WORKER_SESSION}"
  stop_canonical_worker
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
    if ! wait_for_port_release "${BACKEND_PORT}" 30 0.5; then
      log_info "backend port ${BACKEND_PORT} release timeout before launch"
      exit 1
    fi
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

if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "worker" ]]; then
  if ! wait_for_http_200 "http://127.0.0.1:${BACKEND_PORT}/api/health" 24 0.5; then
    log_info "worker requires a healthy API snapshot reader; backend health unavailable"
    exit 1
  fi
  if tmux has-session -t "${WORKER_SESSION}" 2>/dev/null; then
    log_info "worker already supervised in session ${WORKER_SESSION}; skipping duplicate launch"
  else
    tmux new-session -d -s "${WORKER_SESSION}" \
      "cd '${ROOT_DIR}' && ASTRA_PROCESS_ROLE=worker PYTHONDONTWRITEBYTECODE=1 PYTHONPYCACHEPREFIX='/tmp/astra_worker_pycache_$(date +%s)' '${ROOT_DIR}/venv/bin/python' -B -m engine.paper_autopilot_worker >> '${STATE_DIR}/worker.log' 2>&1"
    log_info "dedicated worker session launched: ${WORKER_SESSION}"
  fi
  local_worker_attempt=0
  while [[ "${local_worker_attempt}" -lt 24 ]]; do
    if [[ -f "${STATE_DIR}/astra_worker_runtime_state_v1.json" ]] && grep -q 'PAPER_AUTOPILOT_WORKER' "${STATE_DIR}/astra_worker_runtime_state_v1.json" 2>/dev/null; then
      break
    fi
    sleep 0.5
    local_worker_attempt=$((local_worker_attempt + 1))
  done
  if [[ "${local_worker_attempt}" -ge 24 ]]; then
    log_info "worker did not publish canonical runtime snapshot"
    exit 1
  fi
fi

if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "frontend" ]]; then
  FRONTEND_CMD="cd '${ROOT_DIR}/astra_dashboard/ui' && "
  FRONTEND_CMD+="ASTRA_VITE_API_TARGET='${VITE_PROXY_TARGET}' "
  FRONTEND_CMD+="ASTRA_VITE_ALLOWED_HOSTS='${VITE_ALLOWED_HOSTS}' "
  FRONTEND_CMD+="ASTRA_FRONTEND_HOST='${FRONTEND_HOST}' ASTRA_FRONTEND_PORT='${FRONTEND_PORT}' "
  if [[ -n "${ASTRA_UI_API_BASE_URL:-}" ]]; then
    FRONTEND_CMD+="VITE_API_BASE_URL='${ASTRA_UI_API_BASE_URL}' "
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
    rotate_frontend_log
    tmux new-session -d -s "${FRONTEND_SESSION}" "${FRONTEND_CMD} >> '${STATE_DIR}/frontend.log' 2>&1"
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
  if wait_for_http_200 "http://127.0.0.1:${FRONTEND_PORT}/api/health" 24 0.5; then
    log_info "frontend /api/health proxy responded with 200"
  else
    log_info "frontend /api/health proxy did not reach 200 after startup"
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
if [[ "${START_COMPONENT}" == "all" || "${START_COMPONENT}" == "worker" ]]; then
  log_info "  - ${WORKER_SESSION}"
fi
LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
TAILSCALE_IP="$(tailscale ip -4 2>/dev/null | head -n 1 || true)"
log_info "backend expected (local proxy target): http://127.0.0.1:${BACKEND_PORT}"
log_info "frontend local URL: http://127.0.0.1:${FRONTEND_PORT}"
[[ -n "${LAN_IP}" ]] && log_info "frontend LAN URL: http://${LAN_IP}:${FRONTEND_PORT}"
[[ -n "${TAILSCALE_IP}" ]] && log_info "frontend Tailscale URL: http://${TAILSCALE_IP}:${FRONTEND_PORT}"
