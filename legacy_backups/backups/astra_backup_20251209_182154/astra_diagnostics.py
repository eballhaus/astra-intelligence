#!/usr/bin/env python3
"""
Astra Diagnostics — Pre-flight System Check
Ensures dashboard modules compile and import cleanly.
"""

import importlib
import traceback
import compileall
import sys
from pathlib import Path

MODULES = [
    "astra_core.ui.dashboard.tab_dashboard",
    "astra_core.ui.dashboard.dashboard_cards",
    "astra_core.ui.dashboard.dashboard_chart",
    "astra_core.ui.dashboard.dashboard_data",
    "astra_core.ui.dashboard.dashboard_sidebar",
    "astra_core.ui.dashboard.dashboard_summary",
    "astra_core.fetch_core.fetch_unified",
    "astra_core.guardian.guardian_v6",
]


def run_diagnostics():
    print("🧩 Astra Diagnostics — Pre-flight System Check\n")
    base_path = Path(__file__).resolve().parent
    print(f"📁 Project root: {base_path}\n")

    # 1️⃣ Syntax compile check
    print("🔍 Checking Python syntax ...")
    compileall.compile_dir(str(base_path / "astra_modules"), quiet=1)
    print("✅ Syntax check completed.\n")

    # 2️⃣ Import verification
    passed, failed = [], []
    for mod in MODULES:
        try:
            importlib.import_module(mod)
            print(f"✅ {mod} OK")
            passed.append(mod)
        except Exception as e:
            print(f"🚨 {mod} failed: {e}")
            traceback.print_exc(limit=1)
            failed.append(mod)
            print("-" * 50)

    # 3️⃣ Report summary
    print("\n───────────────────────────────────────────────")
    print(f"✅ Passed: {len(passed)} modules")
    print(f"❌ Failed: {len(failed)} modules")
    print("───────────────────────────────────────────────")
    if failed:
        print("⚠️  Fix above modules before launching Streamlit.")
        sys.exit(1)
    else:
        print("🟢 All systems go! Astra Dashboard is safe to launch.\n")


if __name__ == "__main__":
    run_diagnostics()
