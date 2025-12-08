#!/usr/bin/env bash
# ============================================================
# Astra Intelligence — Full System Diagnostic (Colorized v3)
# ============================================================
# Launches backend, tests API client, keys, and external APIs.
# Works cleanly in zsh, bash, and macOS Terminal with UTF-8.
# ============================================================

export LC_ALL=en_US.UTF-8
export LANG=en_US.UTF-8

SUMMARY_FILE="astra_test_summary.txt"
> "$SUMMARY_FILE"

echo "🚀 Launching Astra Backend + Full Health Diagnostic..."
kill -9 $(lsof -ti :8000) 2>/dev/null
PID=$(uvicorn astra_modules.astra_backend.main:app --reload > backend_test.log 2>&1 & echo $!)
sleep 3

# 1️⃣ Backend + APIClient Test
echo "🧠 [1/5] Testing Astra backend endpoint + Core API Client ..."
python - <<'PYCODE'
from astra_modules.core import api_client
from astra_modules.guardian.guardian_v6 import guardian_log
import pandas as pd

try:
    guardian_log("[TEST] 🔍 Running api_client.get_market_data('BTCUSD') ...")
    df = api_client.get_market_data("BTCUSD")
    if isinstance(df, pd.DataFrame) and not df.empty:
        guardian_log(f"[TEST] ✅ APIClient returned {len(df)} rows for BTCUSD.")
        print("APIClient=PASS", file=open("astra_test_summary.txt", "a"))
    else:
        guardian_log("[TEST] ❌ APIClient returned no data.")
        print("APIClient=FAIL", file=open("astra_test_summary.txt", "a"))
except Exception as e:
    guardian_log(f"[TEST] 🚨 APIClient test failed: {e}")
    print("APIClient=FAIL", file=open("astra_test_summary.txt", "a"))
PYCODE

# 2️⃣ API Keys Verification
echo "🧩 [2/5] Verifying API key imports ..."
python - <<'PYCODE'
from astra_modules.core import api_keys
from astra_modules.guardian.guardian_v6 import guardian_log

KEYS = {
    "ALPHA_VANTAGE_API_KEY": api_keys.ALPHA_VANTAGE_API_KEY,
    "FMP_API_KEY": api_keys.FMP_API_KEY,
    "FINNHUB_API_KEY": api_keys.FINNHUB_API_KEY,
    "EODHD_API_KEY": api_keys.EODHD_API_KEY,
    "MORALIS_API_KEY": api_keys.MORALIS_API_KEY,
    "TWELVEDATA_API_KEY": api_keys.TWELVEDATA_API_KEY,
}

guardian_log("[TEST] 🔑 Verifying API keys ...")
for name, key in KEYS.items():
    if key and key.strip() and "demo" not in key.lower():
        guardian_log(f"[TEST] ✅ OK ({name})")
        print(f"{name}=PASS", file=open("astra_test_summary.txt", "a"))
    else:
        guardian_log(f"[TEST] ❌ Invalid ({name})")
        print(f"{name}=FAIL", file=open("astra_test_summary.txt", "a"))
PYCODE

# 3️⃣ External API Module Tests
echo "🧠 [3/5] Testing each external API adapter ..."
python - <<'PYCODE'
from astra_modules.apis import (
    astra_api_alpha_vantage,
    astra_api_fmp,
    astra_api_finnhub,
    astra_api_eodhd,
    astra_api_moralis,
    astra_api_twelvedata,
)
from astra_modules.guardian.guardian_v6 import guardian_log

symbol = "BTCUSD"
modules = {
    "AlphaVantage": astra_api_alpha_vantage,
    "FMP": astra_api_fmp,
    "Finnhub": astra_api_finnhub,
    "EODHD": astra_api_eodhd,
    "Moralis": astra_api_moralis,
    "TwelveData": astra_api_twelvedata,
}

for name, module in modules.items():
    try:
        guardian_log(f"[TEST] 🔍 Testing {name} API ...")
        df = module.get_data(symbol)
        if not df.empty:
            guardian_log(f"[TEST] ✅ {name} returned {len(df)} rows.")
            print(f"{name}=PASS", file=open("astra_test_summary.txt", "a"))
        else:
            guardian_log(f"[TEST] ⚠️ {name} returned no data.")
            print(f"{name}=FAIL", file=open("astra_test_summary.txt", "a"))
    except Exception as e:
        guardian_log(f"[TEST] 🚨 {name} fetch error: {e}")
        print(f"{name}=FAIL", file=open("astra_test_summary.txt", "a"))
PYCODE

# 4️⃣ Stop Backend
echo "🧹 [4/5] Stopping Astra Backend..."
kill $PID 2>/dev/null; wait $PID 2>/dev/null
sleep 1

# 5️⃣ Generate Colorized Summary Table
echo ""
echo "📊 [5/5] Generating Test Summary Report ..."
echo ""
LINE="═══════════════════════════════════════════════════════"
echo "$LINE"
echo "🧠 Astra Intelligence — Health Diagnostic Summary"
echo "$LINE"
printf "%-25s %-10s\n" "Component" "Status"
printf "%-25s %-10s\n" "───────────────" "────────"

while IFS="=" read -r component result; do
  if [ "$result" = "PASS" ]; then
    status="\033[1;32m✅ PASS\033[0m"
  else
    status="\033[1;31m❌ FAIL\033[0m"
  fi
  printf "%-25s %-10b\n" "$component" "$status"
done < "$SUMMARY_FILE"

echo "$LINE"
echo "✅ Astra Full System Health Diagnostic Complete."

