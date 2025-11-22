"""
Astra Environment Reset Tool (FINAL)
------------------------------------
Run manually whenever Astra breaks.

• Deletes stale .pyc files
• Clears __pycache__
• Ensures ONE version of each module
• Flushes import cache
• Verifies fetch signatures
"""

import os
import shutil
import sys
import importlib
from pathlib import Path


ROOT = Path(__file__).parent
MOD_DIR = ROOT / "astra_modules"


# ===============================================================
# CLEAN .PYC + __pycache__
# ===============================================================

def clear_pycache():
    print("🧹 Clearing __pycache__ folders...")
    removed = 0
    for folder in ROOT.rglob("__pycache__"):
        try:
            shutil.rmtree(folder)
            removed += 1
        except:
            pass
    print(f"   ✔ Removed {removed} pycache folders.\n")


# ===============================================================
# CLEAN IMPORT CACHE
# ===============================================================

def clear_import_cache():
    print("🔄 Clearing import cache...")
    for name in list(sys.modules.keys()):
        if name.startswith("astra_modules"):
            del sys.modules[name]
    importlib.invalidate_caches()
    print("   ✔ Import cache cleared.\n")


# ===============================================================
# VALIDATE SIGNATURES
# ===============================================================

def run_guardian():
    print("🛡 Running environment guardian checks...")
    from astra_modules.guardian.environment_guardian import verify_fetch_signature
    from astra_modules.guardian.environment_guardian import verify_no_stale_imports

    verify_fetch_signature()
    verify_no_stale_imports()

    print("   ✔ Guardian passed. No issues.\n")


# ===============================================================
# MASTER RESET FUNCTION
# ===============================================================

def reset_environment():
    print("\n==========================================")
    print("        ASTRA ENVIRONMENT RESET")
    print("==========================================\n")

    clear_pycache()
    clear_import_cache()
    run_guardian()

    print("✨ Reset complete. Safe to run Astra now.\n")


if __name__ == "__main__":
    reset_environment()
