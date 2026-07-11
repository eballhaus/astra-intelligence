#!/usr/bin/env bash
set -u

# Bounded, read-only crypto paper audit. This never calls the probe route and
# never submits an order; execution remains inside the existing paper gates.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${ASTRA_PYTHON:-$ROOT_DIR/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi
BASE_URL="${ASTRA_DIAGNOSTIC_BASE_URL:-http://127.0.0.1:8000}"

ASTRA_CRYPTO_AUDIT_BASE_URL="$BASE_URL" "$PYTHON_BIN" - <<'PY'
import json
import os
import sys
import urllib.request

base = os.environ["ASTRA_CRYPTO_AUDIT_BASE_URL"].rstrip("/")
paths = [
    "/api/crypto_paper_execution_readiness_v1",
    "/api/alpaca_crypto_runtime_capability_v2",
    "/api/crypto_paper_lane_validation_v1",
    "/api/crypto_candidate_funnel_v1",
    "/api/crypto_position_reconciliation_v1",
    "/api/crypto_broker_truth_accumulation_v1",
]
results = {}
failures = []
for path in paths:
    try:
        with urllib.request.urlopen(base + path, timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("response_not_object")
        results[path] = {
            "status": payload.get("status"),
            "readiness_state": payload.get("readiness_state"),
            "paper_endpoint_verified": payload.get("paper_endpoint_verified"),
            "live_endpoint_rejected": payload.get("live_endpoint_rejected"),
            "no_order_submitted": payload.get("no_order_submitted"),
            "candidate_count": payload.get("candidate_count"),
            "qualified_candidate_count": payload.get("qualified_candidate_count"),
            "crypto_truth_records_total": payload.get("crypto_truth_records_total"),
            "provider_calls_used": payload.get("provider_calls_used", 0),
            "llm_calls_used": payload.get("llm_calls_used", 0),
        }
    except Exception as exc:
        failures.append({"endpoint": path, "error": f"{type(exc).__name__}:{str(exc)[:140]}"})

readiness = results.get("/api/crypto_paper_execution_readiness_v1") or {}
if readiness.get("readiness_state") not in {
    "CRYPTO_PAPER_BLOCKED",
    "CRYPTO_PAPER_READY",
    "CRYPTO_PAPER_READY_NO_ELIGIBLE_TRADE",
    "CRYPTO_PAPER_ACTIVE",
}:
    failures.append({"endpoint": "/api/crypto_paper_execution_readiness_v1", "error": "unexpected_readiness_state"})
if readiness and readiness.get("status") == "PASS" and readiness.get("readiness_state") != "CRYPTO_PAPER_BLOCKED":
    # The readiness builder is intentionally explicit about no action taken.
    # Missing this field is a safety failure even when the HTTP response is OK.
    if readiness.get("no_order_submitted") is not True:
        failures.append({"endpoint": "/api/crypto_paper_execution_readiness_v1", "error": "no_order_proof_missing"})

print(json.dumps({
    "audit": "astra_crypto_audit_v1",
    "base_url": base,
    "status": "PASS" if not failures else "WARNING",
    "endpoints_checked": len(paths),
    "failures": failures,
    "results": results,
    "order_submission_attempted": False,
    "provider_calls_used": 0,
    "llm_calls_used": 0,
    "paper_only_preserved": True,
    "live_trading_changed": False,
}, sort_keys=True))
sys.exit(0 if not failures else 1)
PY
