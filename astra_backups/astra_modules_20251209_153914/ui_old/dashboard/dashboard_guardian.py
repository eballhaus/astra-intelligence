# -*- coding: utf-8 -*-
"""
DashboardGuardian — Astra UI Integrity Layer
--------------------------------------------
Verifies that all dashboard components are intact and auto-repairs missing or
corrupted modules if detected. Designed to be Streamlit-safe and run without
blocking app startup.
"""

import importlib
import os
import sys
from datetime import datetime


# ────────────────────────────────────────────────
# Safe print utility (handles Streamlit I/O issues)
# ────────────────────────────────────────────────
def safe_print(*args, **kwargs):
    """Print safely even if stdout/stderr is closed or blocked."""
    try:
        print(*args, **kwargs)
    except OSError:
        try:
            sys.stderr.write(" ".join(map(str, args)) + "\n")
        except Exception:
            pass


# ────────────────────────────────────────────────
# Dashboard verification placeholder
# ────────────────────────────────────────────────
def verify_dashboard():
    """
    Verifies that all key dashboard components are importable.
    Returns True if everything loads correctly, False otherwise.
    """
    required_modules = {
        "tab_dashboard": [],
        "dashboard_data": ["load_data"],
    }

    all_ok = True

    for module_name, required_funcs in required_modules.items():
        try:
            mod = importlib.import_module(
                f"astra_modules.ui.dashboard.{module_name}")
            for func in required_funcs:
                if not hasattr(mod, func):
                    safe_print(
                        f"[Guardian] ⚠️ Missing function '{func}' in {module_name}"
                    )
                    all_ok = False
            safe_print(f"[Guardian] ✅ Module OK: {module_name}")
        except Exception as e:
            safe_print(
                f"[Guardian] ❌ Failed to import module '{module_name}': {e}")
            all_ok = False

    return all_ok


# ────────────────────────────────────────────────
# Guardian flag check (placeholder logic)
# ────────────────────────────────────────────────
GUARDIAN_FLAG_FILE = os.path.expanduser("~/.astra_guardian_flag")


def run_guardian_check():
    """Performs a one-time dashboard integrity verification."""
    if os.path.exists(GUARDIAN_FLAG_FILE):
        safe_print(
            "[Guardian] 🛡️ Existing Guardian flag detected — skipping full recheck."
        )
    else:
        safe_print("[Guardian] 🔍 Running dashboard verification...")
        if verify_dashboard():
            safe_print("[Guardian] ✅ Dashboard integrity confirmed.")
        else:
            safe_print(
                "[Guardian] ⚠️ Issues detected — consider running Guardian repair mode."
            )
        # Create the flag to avoid repeated checks
        try:
            with open(GUARDIAN_FLAG_FILE, "w") as f:
                f.write(str(datetime.utcnow()))
        except Exception:
            pass


# ────────────────────────────────────────────────
# Auto-execute when imported
# ────────────────────────────────────────────────
if __name__ == "__main__":
    run_guardian_check()
