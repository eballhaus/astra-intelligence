"""
tab_loader_trace.py
----------------------------------------------------
Traces Astra's dashboard tab import system to identify
the exact reason for '❌ Failed to load tab module' errors.
"""

import os
import sys
import importlib
from astra_modules.guardian.environment_guardian import safe_import

def trace_tab_load(tab_name="tab_dashboard"):
    print("\n🔍 Guardian Tab Load Trace")
    print("--------------------------------------------------")
    print(f"🧭 Current Working Directory: {os.getcwd()}")
    print(f"📦 sys.path:")
    for p in sys.path:
        print("   ", p)

    print("\n📘 Attempting safe_import for:", tab_name)
    module = safe_import(f"astra_modules.ui.{tab_name}")

    if module is None:
        print(f"❌ safe_import failed for astra_modules.ui.{tab_name}")
        print("--------------------------------------------------")
        return

    print(f"✅ safe_import succeeded for {module.__name__}")
    if hasattr(module, "render_tab"):
        print("   ↳ Found function: render_tab ✅")
    elif hasattr(module, "render"):
        print("   ↳ Found function: render ⚠️ (rename recommended)")
    else:
        print("   ⚠️ No render_tab() or render() found in module.")

    print("--------------------------------------------------")

if __name__ == "__main__":
    trace_tab_load()
