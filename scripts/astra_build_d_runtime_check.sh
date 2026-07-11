#!/usr/bin/env bash
set -u

# Read-only Build D runtime gate. It validates existing service wrappers and the
# canonical Copilot path without writing state or invoking provider actions.
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BASE_URL="${ASTRA_DIAGNOSTIC_BASE_URL:-http://127.0.0.1:8000}"
WEB_URL="${ASTRA_WEB_BASE_URL:-http://127.0.0.1:5173}"
PYTHON_BIN="${ASTRA_PYTHON:-$ROOT_DIR/venv/bin/python}"
if [ ! -x "$PYTHON_BIN" ]; then
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" - "$BASE_URL" "$WEB_URL" <<'PY'
import json
import sys
import urllib.request

backend = sys.argv[1].rstrip("/")
web = sys.argv[2].rstrip("/")
paths = [
    ("backend_health", backend + "/api/health"),
    ("web_proxy_health", web + "/api/health"),
    ("canonical_copilot", backend + "/api/astra_copilot_suite_v1?limit=5"),
]

results = {}
for name, url in paths:
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results[name] = {"ok": isinstance(payload, dict), "status": getattr(response, "status", 200)}
        if name == "canonical_copilot":
            results[name]["recommendation_count"] = len(payload.get("recommendations") or payload.get("top_actions") or [])
            results[name]["provider_calls_used"] = payload.get("provider_calls_used", 0)
            results[name]["llm_calls_used"] = payload.get("llm_calls_used", 0)
            results[name]["behavior_safe_to_apply"] = payload.get("behavior_safe_to_apply", False)
    except Exception as exc:
        results[name] = {"ok": False, "error": f"{type(exc).__name__}: {str(exc)[:160]}"}

failures = [name for name, result in results.items() if not result.get("ok")]
safety = results.get("canonical_copilot", {})
safety_failures = []
if safety.get("provider_calls_used", 0) != 0:
    safety_failures.append("provider_calls_used_not_zero")
if safety.get("llm_calls_used", 0) != 0:
    safety_failures.append("llm_calls_used_not_zero")
if safety.get("behavior_safe_to_apply", False) is not False:
    safety_failures.append("behavior_safe_to_apply_not_false")

report = {
    "status": "PASS" if not failures and not safety_failures else "FAIL",
    "backend_url": backend,
    "web_url": web,
    "results": results,
    "failures": failures,
    "safety_failures": safety_failures,
    "runtime_files_written": False,
    "broker_actions_used": 0,
}
print(json.dumps(report, indent=2, sort_keys=True))
sys.exit(0 if report["status"] == "PASS" else 1)
PY
