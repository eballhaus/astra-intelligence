#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
cd "${ROOT_DIR}"

mkdir -p logs state

echo "[astra-start] starting Astra via persistent tmux runtime"
ASTRA_REMOTE_MODE="${ASTRA_REMOTE_MODE:-1}" bash "${ROOT_DIR}/start_astra_persistent.sh"
