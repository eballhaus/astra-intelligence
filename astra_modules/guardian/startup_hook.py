"""
🧩 Guardian Startup Hook
------------------------------------------------
Ensures GuardianV6 initializes before any Astra Intelligence system starts.
Runs self-checks, dependency verification, and safe Guardian injection.
"""

import os
import sys
import importlib
from datetime import datetime

# Ensure consistent import path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../"))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ============================================================
# 🧠 Guardian Core Import
# ============================================================

try:
    from astra_core.guardian import guardian_v6
except Exception as e:
    raise ImportError(f"Failed to import guardian_v6: {e}") from e


# ============================================================
# 🚀 Guardian Initialization
# ============================================================

def initialize_guardian():
    """
    Initialize GuardianV6 and perform startup checks.
    Returns the guardian_v6 module reference on success.
    """
    try:
        guardian_instance = guardian_v6
        guardian_v6.guardian_log("🔐 Guardian Startup Hook initialized successfully.")
        guardian_v6.guardian_log(f"📁 Guardian root directory: {guardian_v6.root_dir}")
        guardian_v6.guardian_log(f"🧩 Guardian log file: {guardian_v6.GUARDIAN_LOG_PATH}")
        return guardian_instance
    except Exception as e:
        raise ImportError(f"Failed to initialize guardian_v6: {e}") from e


# ============================================================
# 🧩 Dependency Check
# ============================================================

def verify_core_modules():
    """Verify that Astra core dependencies are available before runtime."""
    modules = [
        "astra_core.fetch_core.fetch_unified",
        "astra_core.ui.dashboard.dashboard_data",
        "astra_core.ui.dashboard.dashboard_chart",
        "astra_core.guardian.guardian_v6",
    ]
    missing = []
    for mod in modules:
        try:
            importlib.import_module(mod)
            guardian_v6.guardian_log(f"✅ Verified module: {mod}")
        except Exception as e:
            guardian_v6.guardian_log(f"🚨 Missing or failed module: {mod} ({e})", level="error")
            missing.append(mod)
    if missing:
        guardian_v6.guardian_log(f"⚠️ Some modules failed verification: {missing}", level="warning")
    else:
        guardian_v6.guardian_log("🟢 All core modules verified successfully.")


# ============================================================
# 🩺 Startup Diagnostics
# ============================================================

def run_startup_diagnostics():
    """Run Guardian-level system diagnostics at startup."""
    guardian_v6.guardian_log("🩺 Running Guardian startup diagnostics...")
    try:
        verify_core_modules()
        guardian_v6.guardian_log("🧠 Guardian startup diagnostics completed successfully.")
        return True
    except Exception as e:
        guardian_v6.guardian_log(f"❌ Guardian diagnostics failed: {e}", level="error")
        return False


# ============================================================
# ⏱ Entry Point
# ============================================================

if __name__ == "__main__":
    guardian = initialize_guardian()
    guardian.guardian_log("🚀 Guardian Startup Hook executing from main context.")
    run_startup_diagnostics()
    guardian.guardian_log("✅ Guardian Startup Hook complete.")
