#!/bin/bash
set -e

echo "🚀 Launching Astra Backend + Full Health Diagnostic v4..."

# 1️⃣ Kill any process using port 8000 (backend)
kill -9 $(lsof -ti :8000) 2>/dev/null || true

# 2️⃣ Start the backend in the background
uvicorn astra_modules.astra_backend.main:app --reload > /dev/null 2>&1 &
PID=$!
sleep 3

# 3️⃣ Prepare directories
LOG_DIR="astra_diagnostics"
AUDIT_FILE="guardian_audit.json"
SUMMARY_FILE="$LOG_DIR/astra_test_summary.txt"
mkdir -p "$LOG_DIR"

# 4️⃣ Run tests and save results
echo "🧠 [1/5] Testing Astra backend + Core systems..."
python - <<'PYCODE'
from astra_modules.core import api_client
from astra_modules.guardian.guardian_v6 import GuardianV7
import json, os, datetime

guardian = GuardianV7()
summary = {}
timestamp = datetime.datetime.now().isoformat()

try:
    df = api_client.get_market_data("BTCUSD")
    summary["APIClient"] = "PASS" if not df.empty else "FAIL"
except Exception as e:
    summary["APIClient"] = "FAIL"
    print("[ERROR] APIClient test failed:", e)

# Test API keys
from astra_modules.core import api_keys
for key_name in [
    "ALPHA_VANTAGE_API_KEY",
    "FMP_API_KEY",
    "FINNHUB_API_KEY",
    "EODHD_API_KEY",
    "MORALIS_API_KEY",
    "TWELVEDATA_API_KEY",
]:
    summary[key_name] = "PASS" if getattr(api_keys, key_name, None) else "FAIL"

# Test external adapters
adapters = {
    "AlphaVantage": "astra_modules.apis.astra_api_alpha_vantage",
    "FMP": "astra_modules.apis.astra_api_fmp",
    "Finnhub": "astra_modules.apis.astra_api_finnhub",
    "EODHD": "astra_modules.apis.astra_api_eodhd",
    "Moralis": "astra_modules.apis.astra_api_moralis",
    "TwelveData": "astra_modules.apis.astra_api_twelvedata",
}

for name, module_path in adapters.items():
    try:
        mod = __import__(module_path, fromlist=["*"])
        if hasattr(mod, "get_data"):
            df = mod.get_data("BTCUSD")
            summary[name] = "PASS" if df is not None and not df.empty else "FAIL"
        else:
            summary[name] = "FAIL"
    except Exception as e:
        summary[name] = "FAIL"
        print(f"[WARN] {name} test failed:", e)

# Save summary to text file
os.makedirs("astra_diagnostics", exist_ok=True)
with open("astra_diagnostics/astra_test_summary.txt", "w") as f:
    for k, v in summary.items():
        f.write(f"{k}={v}\n")

# Save audit to JSON
audit_path = "astra_diagnostics/guardian_audit.json"
if os.path.exists(audit_path):
    with open(audit_path, "r") as f:
        existing = json.load(f)
else:
    existing = []

entry = {"timestamp": timestamp, "summary": summary}
existing.append(entry)

# Keep last 10 records
existing = existing[-10:]

with open(audit_path, "w") as f:
    json.dump(existing, f, indent=2)

print("✅ Audit logged to", audit_path)
PYCODE

# 5️⃣ Stop backend
echo "🧹 [4/5] Stopping Astra Backend..."
kill $PID 2>/dev/null || true
wait $PID 2>/dev/null || true

# 6️⃣ Display summary table
echo "📊 [5/5] Generating Test Summary Report ..."
echo ""
echo "═══════════════════════════════════════════════════════"
echo "🧠 Astra Intelligence — Health Diagnostic Summary"
echo "═══════════════════════════════════════════════════════"
printf "%-25s %-10s\n" "Component" "Status"
printf "%-25s %-10s\n" "───────────────" "────────"

while IFS="=" read -r component result; do
  status="❌ FAIL"
  [ "$result" = "PASS" ] && status="✅ PASS"
  printf "%-25s %-10s\n" "$component" "$status"
done < "$SUMMARY_FILE"

echo "═══════════════════════════════════════════════════════"
echo "✅ Astra Full System Health Diagnostic v4 Complete."
echo "📁 Logged in: $LOG_DIR/guardian_audit.json"

