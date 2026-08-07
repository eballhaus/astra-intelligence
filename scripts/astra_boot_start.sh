#!/bin/bash
set -euo pipefail

# Boot-only launcher: it intentionally supervises backend and worker without
# a terminal multiplexer or a GUI login. The deployment manifest makes this runtime the one
# canonical owner after an explicit controlled handoff.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ASTRA_STATE_ROOT:-${ROOT_DIR}/state}"
LOG_DIR="${ROOT_DIR}/logs"
PYTHON_BIN="${ROOT_DIR}/venv/bin/python"
COMPONENT="${ASTRA_START_COMPONENT:-}"

mkdir -p "${STATE_DIR}" "${LOG_DIR}"

if [[ "${COMPONENT}" != "backend" && "${COMPONENT}" != "worker" ]]; then
  echo "[astra-boot-start] unsupported component: ${COMPONENT}" >&2
  exit 64
fi

worker_is_running() {
  local pid command
  [[ -f "${STATE_DIR}/astra_worker_runtime_state_v1.json" ]] || return 1
  pid="$("${PYTHON_BIN}" - "${STATE_DIR}/astra_worker_runtime_state_v1.json" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(int(data.get("active_worker_pid") or data.get("process_id") or 0))
except Exception:
    pass
PY
)"
  [[ "${pid}" =~ ^[0-9]+$ ]] || return 1
  command="$(ps -p "${pid}" -o command= 2>/dev/null || true)"
  [[ "${command}" == *"engine.paper_autopilot_worker"* ]]
}

if [[ "${COMPONENT}" == "backend" ]]; then
  if curl -m 3 -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "[astra-boot-start] backend already healthy"
    exit 0
  fi
  nohup "${ROOT_DIR}/start_astra_backend.sh" >> "${LOG_DIR}/boot_backend_supervisor.log" 2>&1 &
  for _ in {1..40}; do
    curl -m 2 -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && exit 0
    sleep 0.5
  done
  echo "[astra-boot-start] backend did not become healthy" >&2
  exit 1
fi

if ! curl -m 3 -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "[astra-boot-start] worker requires a healthy backend" >&2
  exit 1
fi
if worker_is_running; then
  echo "[astra-boot-start] canonical worker already running"
  exit 0
fi
nohup env ASTRA_PROCESS_ROLE=worker PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPYCACHEPREFIX="/tmp/astra_boot_worker_pycache" \
  "${PYTHON_BIN}" -B -m engine.paper_autopilot_worker >> "${LOG_DIR}/boot_worker.log" 2>&1 &
for _ in {1..40}; do
  worker_is_running && exit 0
  sleep 0.5
done
echo "[astra-boot-start] worker did not publish canonical ownership" >&2
exit 1
