#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UI_DIR="${ROOT_DIR}/astra_dashboard/ui"

grep -q "'/api'" "${UI_DIR}/vite.config.js"
grep -q "ASTRA_VITE_API_TARGET" "${UI_DIR}/vite.config.js"
grep -q 'DEFAULT_API_BASE = ""' "${UI_DIR}/src/apiBase.js"
grep -q "if (!b) return" "${UI_DIR}/src/apiBase.js"
! rg -n 'fetch\("http://(127\.0\.0\.1|localhost):8000' "${UI_DIR}/src" --glob '!**/*.backup*' --glob '!**/*.bak*'
grep -q "frontend /api/health proxy" "${ROOT_DIR}/start_astra_persistent.sh"
grep -q "ASTRA_CORS_ORIGIN_REGEX" "${ROOT_DIR}/server.py"

echo "Astra web access configuration checks passed"
