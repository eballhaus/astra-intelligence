#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
LOG_FILE="${ROOT_DIR}/logs/astra_watchdog.log"

is_port_listening() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"${port}" -sTCP:LISTEN >/dev/null 2>&1
  else
    return 1
  fi
}

http_ok() {
  local url="$1"
  curl -m 5 -sS -o /dev/null -w "%{http_code}" "${url}" 2>/dev/null | grep -Eq '^2[0-9][0-9]$'
}

frontend_ok() {
  curl -m 5 -sS "http://127.0.0.1:5173" 2>/dev/null | head -n 1 | grep -qi "<!doctype html"
}

if is_port_listening 8000; then
  echo "backend running: yes"
else
  echo "backend running: no"
fi

if is_port_listening 5173; then
  echo "frontend running: yes"
else
  echo "frontend running: no"
fi

if http_ok "http://127.0.0.1:8000/api/health"; then
  echo "backend health: ok"
else
  echo "backend health: fail"
fi

if frontend_ok; then
  echo "frontend health: ok"
else
  echo "frontend health: fail"
fi

echo "last watchdog log lines:"
if [[ -f "${LOG_FILE}" ]]; then
  tail -n 20 "${LOG_FILE}"
else
  echo "(watchdog log not created yet)"
fi
