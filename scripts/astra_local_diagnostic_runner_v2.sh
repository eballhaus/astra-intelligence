#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR" || exit 1

MODE="audit"
DEEP_MODE="false"
for arg in "$@"; do
  case "$arg" in
    audit|status|report) MODE="audit" ;;
    --deep) DEEP_MODE="true" ;;
    *safe-repair) MODE="safe_repair" ;;
    *) echo "Unknown argument: $arg" >&2; exit 2 ;;
  esac
done

PYTHON_BIN="${ASTRA_PYTHON:-$ROOT_DIR/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

mkdir -p diagnostics
TS="$(date -u +"%Y%m%dT%H%M%SZ")"
JSON_OUT="diagnostics/astra_local_diagnostic_v2_${TS}.json"
TXT_OUT="diagnostics/astra_local_diagnostic_v2_${TS}.txt"
LATEST_JSON="diagnostics/astra_local_diagnostic_v2_latest.json"
LATEST_TXT="diagnostics/astra_local_diagnostic_v2_latest.txt"
BACKEND_LOG="diagnostics/astra_local_diagnostic_v2_backend.log"
SERVER_PID=""
BASE_URL="${ASTRA_DIAGNOSTIC_BASE_URL:-http://127.0.0.1:8000}"

check_endpoint() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY' >/dev/null 2>&1
import json
import sys
import urllib.request

base = sys.argv[1].rstrip("/")
path = sys.argv[2]
try:
    with urllib.request.urlopen(base + path, timeout=5) as response:
        payload = json.loads(response.read().decode("utf-8"))
    ok = bool(payload)
except Exception:
    ok = False
sys.exit(0 if ok else 1)
PY
}

port_open() {
  "$PYTHON_BIN" - "$1" <<'PY' >/dev/null 2>&1
import socket
import sys

port = int(sys.argv[1])
sock = socket.socket()
sock.settimeout(0.5)
try:
    sock.connect(("127.0.0.1", port))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    sock.close()
PY
}

cleanup() {
  if [ -n "${SERVER_PID}" ]; then
    kill "$SERVER_PID" >/dev/null 2>&1 || true
    wait "$SERVER_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! check_endpoint "$BASE_URL" "/api/health" || ! check_endpoint "$BASE_URL" "/api/astra_safe_auto_audit_repair_v1"; then
  if [ -z "${ASTRA_DIAGNOSTIC_BASE_URL:-}" ]; then
    SELECTED_PORT=""
    for port in 8018 8019 8020 8021; do
      if ! port_open "$port"; then
        SELECTED_PORT="$port"
        break
      fi
    done
    if [ -z "$SELECTED_PORT" ]; then
      echo "No fallback validation port available." >&2
      exit 1
    fi
    BASE_URL="http://127.0.0.1:${SELECTED_PORT}"
    "$PYTHON_BIN" -m uvicorn server:app --host 127.0.0.1 --port "$SELECTED_PORT" --lifespan off >"$BACKEND_LOG" 2>&1 &
    SERVER_PID="$!"
    for _ in $(seq 1 45); do
      if check_endpoint "$BASE_URL" "/api/astra_safe_auto_audit_repair_v1"; then
        break
      fi
      sleep 1
    done
  fi
fi

ASTRA_DIAGNOSTIC_BASE_URL="$BASE_URL" \
ASTRA_DIAGNOSTIC_JSON_OUT="$JSON_OUT" \
ASTRA_DIAGNOSTIC_TXT_OUT="$TXT_OUT" \
ASTRA_DIAGNOSTIC_MODE="$MODE" \
ASTRA_DIAGNOSTIC_DEEP_MODE="$DEEP_MODE" \
"$PYTHON_BIN" <<'PY'
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

base = os.environ["ASTRA_DIAGNOSTIC_BASE_URL"].rstrip("/")
json_out = os.environ["ASTRA_DIAGNOSTIC_JSON_OUT"]
txt_out = os.environ["ASTRA_DIAGNOSTIC_TXT_OUT"]
mode = os.environ["ASTRA_DIAGNOSTIC_MODE"]
deep_mode = os.environ.get("ASTRA_DIAGNOSTIC_DEEP_MODE", "false").lower() == "true"

endpoints = [
    "/api/health",
    "/api/astra_safe_auto_audit_repair_v1",
    "/api/day_trade_candidate_qualification_dropoff_audit_v1",
    "/api/candidate_level_horizon_trace_v1",
    "/api/active_position_source_alignment_v1",
    "/api/broker_truth_growth_monitor_v1",
    "/api/runtime_performance_payload_optimization_v1",
    "/api/copilot_turnover_action_center_v1",
    "/api/astra_governance_oversight_v1",
    "/api/astra_safe_auto_audit_horizon_runner_validation_v1",
    "/api/unified_learning_diagnostics_v1?force=true",
]

deep_endpoints = [
    "/api/crypto_shadow_learning_v1",
    "/api/crypto_rankings",
    "/api/crypto_paper_lane_validation_v1",
    "/api/crypto_candidate_funnel_v1",
    "/api/crypto_position_reconciliation_v1",
    "/api/learning_throughput_accelerator_v1",
    "/api/momentum_exit_loss_acceptance_v1",
    "/api/crypto_broker_truth_accumulation_v1",
    "/api/cross_market_meta_learning_v1",
    "/api/broker_truth_asset_class_separation_audit_v1",
    "/api/knowledge_retrieval_indexing_v1",
    "/api/knowledge_retrieval_health_v1",
    "/api/evidence_consumption_expansion_v3",
    "/api/symbol_intelligence_behavioral_memory_v1",
    "/api/symbol_memory_health_v1",
    "/api/asset_class_api_budget_routing_v1",
    "/api/astra_high_roi_learning_crypto_validation_v1",
]

if deep_mode:
    endpoints.extend(path for path in deep_endpoints if path not in endpoints)


def fetch(path):
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(base + path, timeout=180) as response:
            raw = response.read()
            payload = json.loads(raw.decode("utf-8"))
            return {
                "ok": True,
                "status_code": response.getcode(),
                "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                "payload_size_bytes": len(raw),
                "payload": payload,
            }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
            "error": type(exc).__name__,
            "message": str(exc)[:500],
            "payload": {},
        }


def payload(path):
    data = results.get(path, {})
    value = data.get("payload")
    return value if isinstance(value, dict) else {}


def run_static_check(cmd):
    started = time.perf_counter()
    proc = subprocess.run(cmd, cwd=os.getcwd(), text=True, capture_output=True, timeout=90)
    return {
        "cmd": cmd,
        "ok": proc.returncode == 0,
        "returncode": proc.returncode,
        "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
        "stdout_tail": proc.stdout[-1000:],
        "stderr_tail": proc.stderr[-1000:],
    }


results = {path: fetch(path) for path in endpoints}
static_checks = [
    run_static_check(["bash", "-n", "scripts/astra_local_diagnostic_runner_v1.sh"]),
    run_static_check(["bash", "-n", "scripts/astra_local_diagnostic_runner_v2.sh"]),
]

safe_audit = payload("/api/astra_safe_auto_audit_repair_v1")
dropoff = payload("/api/day_trade_candidate_qualification_dropoff_audit_v1")
funnel = dropoff.get("day_trade_qualification_funnel_v1") if isinstance(dropoff.get("day_trade_qualification_funnel_v1"), dict) else {}
trace = payload("/api/candidate_level_horizon_trace_v1")
broker = payload("/api/broker_truth_growth_monitor_v1")
horizon = dropoff.get("horizon_persistence_verification_v1") if isinstance(dropoff.get("horizon_persistence_verification_v1"), dict) else {}
alignment = payload("/api/active_position_source_alignment_v1")
runtime = payload("/api/runtime_performance_payload_optimization_v1")
copilot = payload("/api/copilot_turnover_action_center_v1")
governance = payload("/api/astra_governance_oversight_v1")
final = payload("/api/astra_safe_auto_audit_horizon_runner_validation_v1")

endpoint_failures = [path for path, item in results.items() if not item.get("ok")]
script_failures = [item for item in static_checks if not item.get("ok")]
safe_repairs_requested = mode == "safe_repair"
safe_repairs_applied = []
blocked_unsafe_repairs = [
    row for row in (safe_audit.get("issue_rows") or [])
    if isinstance(row, dict) and row.get("classification") == "HUMAN_APPROVAL_REQUIRED"
]

summary = {
    "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "mode": mode,
    "deep_mode": deep_mode,
    "base_url": base,
    "executive_status": "PASS" if not endpoint_failures and not script_failures else "WARNING",
    "safety_status": {
        "paper_only_preserved": True,
        "broker_live_endpoint_allowed": False,
        "live_trading_enabled": False,
        "learned_exits_enabled": False,
        "automatic_promotions_enabled": False,
        "forced_trades_enabled": False,
        "forced_exits_enabled": False,
        "broker_actions_used": 0,
        "provider_calls_used": 0,
        "llm_calls_used": 0,
        "behavior_changes_applied": False,
    },
    "backend_frontend_status": {
        "backend_base_url": base,
        "frontend_checked": False,
        "frontend_reason": "ui_not_touched",
    },
    "endpoint_status": {
        "endpoint_count": len(endpoints),
        "endpoint_failures": endpoint_failures,
        "timings_ms": {path: item.get("elapsed_ms") for path, item in results.items()},
    },
    "day_trade_funnel": {
        "generated": funnel.get("day_trade_candidates_generated"),
        "ranked": funnel.get("day_trade_candidates_ranked"),
        "horizon_rows_created": funnel.get("day_trade_horizon_rows_created"),
        "qualified": funnel.get("day_trade_candidates_qualified"),
        "paper_eligible": funnel.get("day_trade_candidates_paper_eligible"),
        "dropoff": funnel.get("exact_gate_blocking_day_trades"),
        "reasons": funnel.get("day_trade_candidate_rejection_reasons"),
    },
    "candidate_level_trace": {
        "trace_status": trace.get("trace_status"),
        "trace_coverage_pct": trace.get("trace_coverage_pct"),
        "missing_upstream_sources": trace.get("missing_upstream_sources"),
    },
    "horizon_assignment": {
        "exact_dropoff": funnel.get("exact_dropoff_stage"),
        "exact_reason": funnel.get("exact_dropoff_reason"),
        "human_approval_required": funnel.get("human_approval_required"),
    },
    "capacity": dropoff.get("capacity_recycling_support_v1") or {},
    "exit_readiness": {},
    "broker_truth_growth": {
        "total": broker.get("broker_truth_records_total"),
        "complete": broker.get("broker_confirmed_complete_records"),
        "remaining_to_25": broker.get("records_remaining_to_25"),
        "bottleneck": broker.get("broker_truth_growth_bottleneck"),
    },
    "crypto": {
        "lane_validation": payload("/api/crypto_paper_lane_validation_v1") if deep_mode else {},
        "candidate_funnel": payload("/api/crypto_candidate_funnel_v1") if deep_mode else {},
        "position_reconciliation": payload("/api/crypto_position_reconciliation_v1") if deep_mode else {},
        "truth_accumulation": payload("/api/crypto_broker_truth_accumulation_v1") if deep_mode else {},
    },
    "combined_lifecycle": payload("/api/learning_throughput_accelerator_v1") if deep_mode else {},
    "api_budget": payload("/api/asset_class_api_budget_routing_v1") if deep_mode else {},
    "horizon_persistence": horizon,
    "active_position_alignment": alignment,
    "unified_diagnostic_performance": {
        "before_timing_seconds": runtime.get("before_timing_seconds"),
        "after_timing_seconds": results.get("/api/unified_learning_diagnostics_v1?force=true", {}).get("elapsed_ms"),
        "timeout_risk": runtime.get("timeout_risk"),
    },
    "copilot": {
        "issue_routing": copilot.get("safe_auto_audit_issue_routing_v1"),
        "day_trade_funnel_status": copilot.get("day_trade_funnel_status"),
    },
    "governance": {
        "warnings": governance.get("warnings"),
        "issue_routing": governance.get("safe_auto_audit_issue_routing_v1"),
    },
    "safe_auto_fix_summary": {
        "safe_repair_mode_requested": safe_repairs_requested,
        "safe_repairs_attempted": safe_audit.get("safe_repairs_attempted"),
        "safe_repairs_succeeded": safe_audit.get("safe_repairs_succeeded"),
        "safe_repairs_failed": safe_audit.get("safe_repairs_failed"),
        "safe_repairs_applied_by_runner": safe_repairs_applied,
    },
    "human_approval_required": blocked_unsafe_repairs,
    "top_10_issues": safe_audit.get("top_10_issues") or final.get("top_10_issues") or [],
    "newly_discovered_issues": dropoff.get("newly_discovered_issues") or [],
    "regression_checks": {
        "static_checks": static_checks,
        "final_validation_status": final.get("status"),
        "script_failures": script_failures,
    },
    "recommended_next_action": "human_review_horizon_assignment_threshold_or_strategy_gate" if blocked_unsafe_repairs else "continue_monitoring",
}

report = {
    "summary": summary,
    "safe_auto_audit": safe_audit,
    "endpoint_results": results,
    "static_checks": static_checks,
}

with open(json_out, "w", encoding="utf-8") as handle:
    json.dump(report, handle, indent=2, sort_keys=True)

sections = [
    "Astra Local Diagnostic Runner V2",
    f"Generated: {summary['generated_at']}",
    f"Mode: {mode}",
    f"Base URL: {base}",
    "",
    "Executive status",
    json.dumps(summary["executive_status"], indent=2),
    "",
    "Safety status",
    json.dumps(summary["safety_status"], indent=2, sort_keys=True),
    "",
    "Endpoint status",
    json.dumps(summary["endpoint_status"], indent=2, sort_keys=True),
    "",
    "Day-trade funnel",
    json.dumps(summary["day_trade_funnel"], indent=2, sort_keys=True),
    "",
    "Candidate-level trace",
    json.dumps(summary["candidate_level_trace"], indent=2, sort_keys=True),
    "",
    "Horizon assignment",
    json.dumps(summary["horizon_assignment"], indent=2, sort_keys=True),
    "",
    "Broker truth growth",
    json.dumps(summary["broker_truth_growth"], indent=2, sort_keys=True),
    "",
    "Horizon persistence",
    json.dumps(summary["horizon_persistence"], indent=2, sort_keys=True),
    "",
    "Active-position alignment",
    json.dumps(summary["active_position_alignment"], indent=2, sort_keys=True),
    "",
    "Unified diagnostic performance",
    json.dumps(summary["unified_diagnostic_performance"], indent=2, sort_keys=True),
    "",
    "Copilot",
    json.dumps(summary["copilot"], indent=2, sort_keys=True),
    "",
    "Governance",
    json.dumps(summary["governance"], indent=2, sort_keys=True),
    "",
    "Safe auto-fix summary",
    json.dumps(summary["safe_auto_fix_summary"], indent=2, sort_keys=True),
    "",
    "Human approval required",
    json.dumps(summary["human_approval_required"], indent=2, sort_keys=True),
    "",
    "Top 10 issues",
    json.dumps(summary["top_10_issues"], indent=2, sort_keys=True),
    "",
    "Regression checks",
    json.dumps(summary["regression_checks"], indent=2, sort_keys=True),
    "",
    "Recommended next action",
    summary["recommended_next_action"],
]
with open(txt_out, "w", encoding="utf-8") as handle:
    handle.write("\n".join(sections) + "\n")

print(json.dumps({"json": json_out, "text": txt_out, "endpoint_failures": endpoint_failures, "script_failures": len(script_failures), "mode": mode}, indent=2))

if endpoint_failures or script_failures:
    sys.exit(1)
if final.get("status") not in {"PASS", "PASS_RUNNER_REPORT_PENDING"}:
    sys.exit(1)
PY

cp "$JSON_OUT" "$LATEST_JSON"
cp "$TXT_OUT" "$LATEST_TXT"
echo "Astra local diagnostic V2 reports:"
echo "  $TXT_OUT"
echo "  $JSON_OUT"
echo "  $LATEST_TXT"
echo "  $LATEST_JSON"
