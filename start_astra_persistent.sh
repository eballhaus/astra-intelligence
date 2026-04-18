#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${ROOT_DIR}/state"

BACKEND_SESSION="${ASTRA_BACKEND_TMUX_SESSION:-astra_backend}"
FRONTEND_SESSION="${ASTRA_FRONTEND_TMUX_SESSION:-astra_frontend}"

BACKEND_PORT="${ASTRA_BACKEND_PORT:-8000}"
FRONTEND_PORT="${ASTRA_FRONTEND_PORT:-5173}"

BACKEND_HOST="${ASTRA_BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${ASTRA_FRONTEND_HOST:-127.0.0.1}"

if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  BACKEND_HOST="${ASTRA_BACKEND_HOST:-0.0.0.0}"
  FRONTEND_HOST="${ASTRA_FRONTEND_HOST:-0.0.0.0}"
fi

mkdir -p "${STATE_DIR}"

log_info() {
  echo "[start_astra_persistent] $*"
}

if ! command -v tmux >/dev/null 2>&1; then
  log_info "tmux is required but not installed."
  exit 1
fi

# Keep lifecycle consistent and avoid duplicate owners.
bash "${ROOT_DIR}/stop_astra_persistent.sh" >/dev/null 2>&1 || true
log_info "pre-start cleanup invoked via stop_astra_persistent.sh"

tmux new-session -d -s "${BACKEND_SESSION}" \
  "cd '${ROOT_DIR}' && ASTRA_BACKEND_HOST='${BACKEND_HOST}' ASTRA_BACKEND_PORT='${BACKEND_PORT}' ASTRA_REMOTE_MODE='${ASTRA_REMOTE_MODE:-0}' bash '${ROOT_DIR}/start_astra_backend.sh'"
log_info "backend session launched: ${BACKEND_SESSION} (${BACKEND_HOST}:${BACKEND_PORT})"

API_BASE_URL="${ASTRA_UI_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}}"
if [[ "${ASTRA_REMOTE_MODE:-0}" == "1" ]]; then
  API_BASE_URL="${ASTRA_UI_API_BASE_URL:-}"
fi

FRONTEND_CMD="cd '${ROOT_DIR}/astra_dashboard/ui' && "
if [[ -n "${API_BASE_URL}" ]]; then
  FRONTEND_CMD+="VITE_API_BASE_URL='${API_BASE_URL}' "
fi
if [[ -n "${ASTRA_REMOTE_ACCESS_TOKEN:-}" ]]; then
  FRONTEND_CMD+="VITE_REMOTE_ACCESS_TOKEN='${ASTRA_REMOTE_ACCESS_TOKEN}' "
fi
FRONTEND_CMD+="npm run dev -- --host '${FRONTEND_HOST}' --port '${FRONTEND_PORT}'"

frontend_port_in_use=0
if command -v lsof >/dev/null 2>&1; then
  if lsof -nP -iTCP:"${FRONTEND_PORT}" -sTCP:LISTEN >/dev/null 2>&1; then
    frontend_port_in_use=1
  fi
fi

if [[ "${frontend_port_in_use}" == "1" ]]; then
  log_info "frontend port ${FRONTEND_PORT} already in use; skipping duplicate frontend launch"
  log_info "frontend session not started: ${FRONTEND_SESSION}"
else
  tmux new-session -d -s "${FRONTEND_SESSION}" "${FRONTEND_CMD}"
  log_info "frontend session launched: ${FRONTEND_SESSION} (${FRONTEND_HOST}:${FRONTEND_PORT})"
fi

log_info "started tmux sessions summary:"
log_info "  - ${BACKEND_SESSION}"
if [[ "${frontend_port_in_use}" == "1" ]]; then
  log_info "  - ${FRONTEND_SESSION} (skipped: port in use)"
else
  log_info "  - ${FRONTEND_SESSION}"
fi
log_info "backend expected: http://127.0.0.1:${BACKEND_PORT}"
log_info "frontend expected: http://127.0.0.1:${FRONTEND_PORT}"
