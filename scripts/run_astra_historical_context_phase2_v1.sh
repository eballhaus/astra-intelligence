#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STATE_DIR="${ASTRA_STATE_DIR:-/Users/Shared/AstraRuntime/state}"
exec "${PYTHON_BIN:-$ROOT/venv/bin/python}" -u "$ROOT/scripts/astra_historical_context_phase2_v1.py" --state-dir "$STATE_DIR"
