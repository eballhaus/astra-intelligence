#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ROOT_DIR}/state"

port_status() {
  local port="$1"
  if lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "up"
  else
    echo "down"
  fi
}

echo "Astra web status"
echo "  frontend : $(port_status 5173) (http://127.0.0.1:5173)"
echo "  backend  : $(port_status 8000) (proxy target http://127.0.0.1:8000)"
if curl -m 3 -fsS http://127.0.0.1:5173/api/health >/tmp/astra_web_health.$$ 2>/dev/null; then
  echo "  /api/health through frontend: healthy"
  rm -f /tmp/astra_web_health.$$
else
  echo "  /api/health through frontend: unavailable"
  rm -f /tmp/astra_web_health.$$
fi
if command -v tmux >/dev/null 2>&1; then
  echo "  backend session: $(tmux has-session -t "${ASTRA_BACKEND_TMUX_SESSION:-astra_backend}" 2>/dev/null && echo present || echo absent)"
  echo "  frontend session: $(tmux has-session -t "${ASTRA_FRONTEND_TMUX_SESSION:-astra_frontend}" 2>/dev/null && echo present || echo absent)"
fi
if [[ -f "${STATE_DIR}/uvicorn.pid" ]]; then echo "  backend pid file: ${STATE_DIR}/uvicorn.pid"; fi
