"""
ASTRADOCTOR 2.0 — Safe Auto-Fix Mode
Fully self-healing diagnostic engine.
"""

import importlib
import traceback
import pandas as pd

from astra_modules.devtools.auto_fix_engine import auto_fix_renderers
from astra_modules.devtools.guardian_sync import sync_guardian


def hr():
    print("=" * 60)


# --------------------------------
# AUTO-FIX PHASE
# --------------------------------
def auto_fix_phase():
    hr()
    print("AUTO-FIX PHASE — Repairing UI + Guardian Imports\n")

    fixes = []
    fixes.extend(auto_fix_renderers())
    fixes.extend(sync_guardian())

    if fixes:
        for f in fixes:
            print("🛠 FIXED:", f)
    else:
        print("✓ No fixes needed — system clean.")

    print()


# --------------------------------
# IMPORT VALIDATION
# --------------------------------
def validate_import(module: str):
    try:
        importlib.import_module(module)
        print("✔ OK:", module)
        return True
    except Exception as e:
        print("❌ FAILED:", module, "→", str(e))
        return False


# --------------------------------
# MASTER DIAGNOSTIC
# --------------------------------
def main():
    print("\nASTRADOCTOR 2.0 — SELF-HEALING MODE\n")
    auto_fix_phase()

    hr()
    print("IMPORT VALIDATION\n")

    modules = [
        "astra_modules.scanners.smart_scan",
        "astra_modules.scanners.hybrid_scan",
        "astra_modules.fetch_core.fetch_unified",
        "astra_modules.ui.tab_dashboard",
        "astra_modules.ui.tab_predictions",
        "astra_modules.ui.tab_learning",
    ]

    all_ok = True
    for m in modules:
        if not validate_import(m):
            all_ok = False

    hr()

    if all_ok:
        print("✨ SYSTEM CLEAN — Astra is ready to launch.")
    else:
        print("⚠ Some modules failed to import — check above errors.")

    print("\nDone.\n")


if __name__ == "__main__":
    main()
