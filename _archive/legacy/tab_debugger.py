"""
Guardian Tab Debugger
----------------------------------------------------
Diagnoses why tab modules fail to load in Astra.
"""

import importlib
import traceback


def debug_tab_import(tab_name="tab_dashboard"):
    print(f"\n🔍 Debugging tab import: {tab_name}")
    print("--------------------------------------------------")
    search_paths = ["core.ui", "core.tabs"]

    for path in search_paths:
        full_name = f"{path}.{tab_name}"
        try:
            module = importlib.import_module(full_name)
            print(f"✅ Successfully imported: {full_name}")
            if hasattr(module, "render_tab"):
                print("   ↳ Found function: render_tab() ✅")
            elif hasattr(module, "render"):
                print("   ↳ Found function: render() ⚠️ (rename recommended)")
            else:
                print("   ⚠️ No render_tab() or render() found.")
        except Exception:
            print(f"❌ Failed to import {full_name}")
            traceback.print_exc()
        print("--------------------------------------------------")


if __name__ == "__main__":
    debug_tab_import()
