#!/bin/bash
set -euo pipefail

ROOT_DIR="/Users/eric/Desktop/astra-intelligence-clean"
cd "${ROOT_DIR}"

echo "[astra-stop] stopping Astra persistent runtime"
bash "${ROOT_DIR}/stop_astra_persistent.sh"
