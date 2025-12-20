"""
Astra Sanity Check — Runtime Health Validator
----------------------------------------------
Verifies:
  • Guardian V6 Hybrid operational
  • fetch_core modules import safely
  • utils (safe_df, safe_api_wrapper) available
  • major Astra submodules import correctly
"""

import importlib
import json
import os
import traceback
from datetime import datetime

REPORT = {"timestamp": datetime.utcnow().isoformat(), "modules": {}, "errors": []}
ROOT_DIR = os.path.expanduser("~/astra_guardian_runtime")
os.makedirs(ROOT_DIR, exist_ok=True)
REPORT_FILE = os.path.join(ROOT_DIR, "sanity_report.json")


def check_module(name):
    try:
        importlib.import_module(name)
        REPORT["modules"][name] = "✅ OK"
    except Exception as e:
        REPORT["modules"][name] = f"❌ {e.__class__.__name__}: {e}"
        REPORT["errors"].append(f"{name}: {traceback.format_exc(limit=1)}")


# ==============================================================
# Guardian Core
# ==============================================================
for mod in [
    "guardian.guardian_v6",
    "guardian.guardian_ratewatch",
    "guardian.guardian_defender",
    "guardian.guardian_sentinel",
]:
    check_module(mod)


# ==============================================================
# fetch_core Modules
# ==============================================================
for mod in [
    "fetch_core.fetch_crypto",
    "fetch_core.fetch_stock",
    "fetch_core.fetch_etf",
    "fetch_core.fetch_unified",
    "fetch_core.fetcher",
]:
    check_module(mod)


# ==============================================================
# Utils
# ==============================================================
for mod in [
    "utils.safe_api_wrapper",
    "utils.safe_df",
]:
    check_module(mod)


# ==============================================================
# Astra Subsystems
# ==============================================================
for mod in [
    "engine",
    "forecast",
    "learning",
    "agents",
    "state",
]:
    check_module(mod)


# ==============================================================
# Output
# ==============================================================
with open(REPORT_FILE, "w") as f:
    json.dump(REPORT, f, indent=2)

print("\n==============================")
print("  ASTRA SANITY CHECK REPORT")
print("==============================")
for name, result in REPORT["modules"].items():
    print(f"{name:40} {result}")

if REPORT["errors"]:
    print("\n⚠️  ERRORS FOUND:")
    for err in REPORT["errors"]:
        print("   ", err.strip())

print(f"\n🧾 Report saved to: {REPORT_FILE}")
print("✅ Sanity check complete.\n")
