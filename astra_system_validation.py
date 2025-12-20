#!/usr/bin/env python3
"""
Astra Intelligence – Post-Migration System Validation
Checks that all core modules import and link correctly after consolidation.
"""

import importlib
import traceback
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent
LOG_FILE = (
    ROOT / "astra_logs" / f"astra_validation_log_{datetime.now():%Y%m%d_%H%M%S}.txt"
)
LOG_FILE.parent.mkdir(exist_ok=True)

modules = {
    "Guardian": "astra_modules.guardian.guardian_v7",
    "Engine": "astra_modules.engine.orchestrator",
    "Fetch": "astra_modules.fetch.fetch_unified",
    "UI": "astra_modules.ui.dashboard.tab_dashboard",
    "State": "astra_modules.state.state_bundle_builder",
    "Agents": "astra_modules.agents.momentum_agent",
    "Forecast": "astra_modules.forecast.forecast_engine",
    "Learning": "astra_modules.learning.replay_buffer",
    "Utils": "astra_modules.utils.safe_df",
}

results = {}


def test_import(name, module_path):
    try:
        mod = importlib.import_module(module_path)
        results[name] = "✅ OK"
        return True
    except Exception as e:
        results[name] = f"❌ Import error: {e.__class__.__name__}"
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n{name} ({module_path}) FAILED:\n{traceback.format_exc()}\n")
        return False


print("🔍 Running Astra Intelligence System Validation...\n")

for name, module_path in modules.items():
    test_import(name, module_path)

# Dependency checks
if results["Guardian"] == "✅ OK" and results["Engine"] == "✅ OK":
    try:
        import astra_modules.engine.orchestrator as orch

        results["Guardian→Engine link"] = (
            "✅ OK" if hasattr(orch, "Orchestrator") else "⚠️ No Orchestrator class"
        )
    except Exception as e:
        results["Guardian→Engine link"] = f"❌ Failed: {e.__class__.__name__}"

# Print summary
print("📊 Astra Intelligence Module Validation Summary:\n")
for name, status in results.items():
    print(f"{name:25s} {status}")

with open(LOG_FILE, "a", encoding="utf-8") as f:
    f.write("\n📊 Astra Intelligence Validation Summary:\n")
    for name, status in results.items():
        f.write(f"{name:25s} {status}\n")

print(f"\n🧾 Full log written to: {LOG_FILE}")
print("\n✅ Validation complete.")
