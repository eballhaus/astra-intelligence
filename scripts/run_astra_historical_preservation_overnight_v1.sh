#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/venv/bin/python" -u "$ROOT/scripts/astra_historical_preservation_overnight_v1.py" "$@"
