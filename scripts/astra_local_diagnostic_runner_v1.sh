#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

BASE_URL="${ASTRA_DIAGNOSTIC_BASE_URL:-http://127.0.0.1:8000}"
PYTHON_BIN="${ASTRA_PYTHON:-$ROOT_DIR/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

mkdir -p diagnostics
TS="$(date -u +"%Y%m%dT%H%M%SZ")"
JSON_OUT="diagnostics/astra_local_diagnostic_${TS}.json"
TXT_OUT="diagnostics/astra_local_diagnostic_${TS}.txt"
LATEST_JSON="diagnostics/astra_local_diagnostic_latest.json"
LATEST_TXT="diagnostics/astra_local_diagnostic_latest.txt"
BACKEND_LOG="diagnostics/astra_local_diagnostic_backend.log"
SERVER_PID=""

health_ok() {
  "$PYTHON_BIN" - "$BASE_URL" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
try:
    with urllib.request.urlopen(base + "/api/health", timeout=4) as response:
        payload = json.loads(response.read().decode("utf-8"))
    ok = bool(payload)
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PY
}

cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! health_ok; then
  if [ "$BASE_URL" = "http://127.0.0.1:8000" ]; then
    "$PYTHON_BIN" -m uvicorn server:app --host 127.0.0.1 --port 8000 --lifespan off >"$BACKEND_LOG" 2>&1 &
    SERVER_PID="$!"
    for _ in $(seq 1 30); do
      if health_ok; then
        break
      fi
      sleep 1
    done
  fi
fi

ASTRA_DIAGNOSTIC_BASE_URL="$BASE_URL" \
ASTRA_DIAGNOSTIC_JSON_OUT="$JSON_OUT" \
ASTRA_DIAGNOSTIC_TXT_OUT="$TXT_OUT" \
"$PYTHON_BIN" <<'PY'
import json
import os
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

base = os.environ["ASTRA_DIAGNOSTIC_BASE_URL"].rstrip("/")
json_out = os.environ["ASTRA_DIAGNOSTIC_JSON_OUT"]
txt_out = os.environ["ASTRA_DIAGNOSTIC_TXT_OUT"]

endpoints = [
    "/api/health",
    "/api/day_trade_candidate_qualification_dropoff_audit_v1",
    "/api/horizon_assignment_tiebreak_runner_validation_v1",
    "/api/capacity_recycling_daytrade_brokertruth_validation_v1",
    "/api/day_trade_scalp_lifecycle_wiring_audit_v1",
    "/api/horizon_turnover_exit_audit_v1",
    "/api/exit_readiness_diagnostics_v1",
    "/api/broker_truth_growth_monitor_v1",
    "/api/copilot_turnover_action_center_v1",
    "/api/astra_governance_oversight_v1",
    "/api/astra_turnover_exit_growth_summary_v1",
    "/api/runtime_performance_payload_optimization_v1",
    "/api/unified_learning_diagnostics_v1?force=true",
]


def fetch(path):
    started = time.perf_counter()
    url = base + path
    try:
        with urllib.request.urlopen(url, timeout=150) as response:
            raw = response.read()
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
            payload = json.loads(raw.decode("utf-8"))
            return {
                "ok": True,
                "status_code": response.getcode(),
                "elapsed_ms": elapsed_ms,
                "payload_size_bytes": len(raw),
                "payload": payload,
            }
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        return {
            "ok": False,
            "elapsed_ms": elapsed_ms,
            "error": type(exc).__name__,
            "message": str(exc)[:500],
            "payload": {},
        }


results = {path: fetch(path) for path in endpoints}


def payload(path):
    data = results.get(path, {})
    p = data.get("payload")
    return p if isinstance(p, dict) else {}


dropoff = payload("/api/day_trade_candidate_qualification_dropoff_audit_v1")
funnel = dropoff.get("day_trade_qualification_funnel_v1") if isinstance(dropoff.get("day_trade_qualification_funnel_v1"), dict) else {}
recycling = dropoff.get("capacity_recycling_support_v1") if isinstance(dropoff.get("capacity_recycling_support_v1"), dict) else {}
broker = payload("/api/broker_truth_growth_monitor_v1")
readiness = payload("/api/exit_readiness_diagnostics_v1")
horizon = dropoff.get("horizon_persistence_verification_v1") if isinstance(dropoff.get("horizon_persistence_verification_v1"), dict) else {}
governance = payload("/api/astra_governance_oversight_v1")
validation = payload("/api/horizon_assignment_tiebreak_runner_validation_v1")
runtime = payload("/api/runtime_performance_payload_optimization_v1")

top_issues = validation.get("top_10_issues") if isinstance(validation.get("top_10_issues"), list) else []
if not top_issues:
    top_issues = [
        {"issue": item, "severity": "watch"}
        for item in (dropoff.get("remaining_bottlenecks") or [])[:10]
    ]

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "base_url": base,
    "endpoint_count": len(endpoints),
    "endpoint_failures": [path for path, item in results.items() if not item.get("ok")],
    "broker_truth": {
        "complete_records": broker.get("broker_confirmed_complete_records"),
        "remaining_to_25": broker.get("remaining_to_25", broker.get("records_remaining_to_25")),
        "remaining_to_50": broker.get("remaining_to_50", broker.get("records_remaining_to_50")),
        "remaining_to_100": broker.get("remaining_to_100", broker.get("records_remaining_to_100")),
        "growth_velocity_7d": broker.get("growth_velocity_7d"),
        "growth_velocity_30d": broker.get("growth_velocity_30d"),
        "bottleneck": broker.get("growth_bottleneck", broker.get("broker_truth_growth_bottleneck")),
    },
    "day_trade_funnel": {
        "generated": funnel.get("day_trade_candidates_generated"),
        "ranked": funnel.get("day_trade_candidates_ranked"),
        "qualified": funnel.get("day_trade_candidates_qualified"),
        "rejected": funnel.get("day_trade_candidates_rejected"),
        "exact_dropoff": funnel.get("exact_gate_blocking_day_trades"),
        "rejection_reasons": funnel.get("day_trade_candidate_rejection_reasons"),
        "misaligned_rejection_reason_detected": funnel.get("misaligned_rejection_reason_detected"),
        "misaligned_rejection_reason_fixed": funnel.get("misaligned_rejection_reason_fixed"),
    },
    "capacity": {
        "raw_open_rows": recycling.get("raw_open_rows"),
        "deduped_active_symbols": recycling.get("deduped_active_symbols"),
        "capacity_utilization": recycling.get("capacity_utilization"),
        "capacity_traps": recycling.get("capital_trapped_count"),
        "replacement_candidates": recycling.get("replacement_candidate_count"),
        "day_trade_capacity_available": recycling.get("day_trade_capacity_available"),
    },
    "exit_readiness": {
        "exit_review": readiness.get("exit_review_count", len(readiness.get("exit_review_candidates") or [])),
        "replace_candidate": readiness.get("replacement_candidate_count", len(readiness.get("replacement_candidates") or [])),
        "stale_review": readiness.get("stale_review_count", len(readiness.get("stale_review_candidates") or [])),
        "watch": readiness.get("watch_count"),
    },
    "horizon": {
        "legacy_missing_horizon_rows": horizon.get("legacy_missing_horizon_records"),
        "new_records_with_horizon": horizon.get("new_records_with_horizon"),
        "horizon_persistence_status": horizon.get("horizon_persistence_status"),
    },
    "safety": {
        "live_trading_enabled": bool(dropoff.get("live_trading_enabled")),
        "learned_exits_enabled": bool(dropoff.get("learned_exits_enabled")),
        "forced_exits_enabled": bool(dropoff.get("forced_exits_enabled")),
        "broker_behavior_changed": bool(dropoff.get("broker_behavior_changed")),
        "provider_calls_used": dropoff.get("provider_calls_used", 0),
        "llm_calls_used": dropoff.get("llm_calls_used", 0),
    },
    "governance": {
        "warnings": governance.get("warnings") or [],
        "top_actions": governance.get("top_5_actions") or [],
    },
    "runtime": {
        "timeout_risk": runtime.get("timeout_risk"),
        "slow_sections_identified": runtime.get("slow_sections_identified") or [],
    },
    "top_10_issues": top_issues[:10],
}

report = {
    "summary": summary,
    "endpoint_results": results,
    "excluded_scan_paths": [
        "archive",
        "_archive",
        "backups",
        "_backup",
        "snapshots",
        "venv",
        ".git",
        "__pycache__",
    ],
}

with open(json_out, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2, sort_keys=True)

lines = [
    "Astra Local Diagnostic Runner V1",
    f"Generated: {summary['generated_at']}",
    f"Base URL: {base}",
    "",
    "Broker Truth",
    json.dumps(summary["broker_truth"], indent=2, sort_keys=True),
    "",
    "Day-Trade Funnel",
    json.dumps(summary["day_trade_funnel"], indent=2, sort_keys=True),
    "",
    "Capacity",
    json.dumps(summary["capacity"], indent=2, sort_keys=True),
    "",
    "Exit Readiness",
    json.dumps(summary["exit_readiness"], indent=2, sort_keys=True),
    "",
    "Horizon",
    json.dumps(summary["horizon"], indent=2, sort_keys=True),
    "",
    "Safety",
    json.dumps(summary["safety"], indent=2, sort_keys=True),
    "",
    "Governance Warnings",
    json.dumps(summary["governance"], indent=2, sort_keys=True),
    "",
    "Runtime",
    json.dumps(summary["runtime"], indent=2, sort_keys=True),
    "",
    "Top 10 Issues",
    json.dumps(summary["top_10_issues"], indent=2, sort_keys=True),
    "",
    "Endpoint Failures",
    json.dumps(summary["endpoint_failures"], indent=2, sort_keys=True),
]
with open(txt_out, "w", encoding="utf-8") as handle:
    handle.write("\n".join(lines) + "\n")

print(json.dumps({"json": json_out, "text": txt_out, "endpoint_failures": summary["endpoint_failures"]}, indent=2))
PY

cp "$JSON_OUT" "$LATEST_JSON"
cp "$TXT_OUT" "$LATEST_TXT"
echo "Astra local diagnostic reports:"
echo "  $TXT_OUT"
echo "  $JSON_OUT"
echo "  $LATEST_TXT"
echo "  $LATEST_JSON"
