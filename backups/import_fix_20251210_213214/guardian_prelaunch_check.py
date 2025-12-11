"""
Astra Guardian — Pre-Launch Check
---------------------------------
Verifies the integrity of core modules before full dashboard startup.
"""

import importlib

from .guardian_v7 import guardian_log


def run_guardian_prelaunch_check():
    modules = [
        "astra_core.fetch_core.fetch_unified",
        "astra_core.ui.dashboard.dashboard_data",
        "astra_core.ui.dashboard.dashboard_chart",
        "astra_core.ui.dashboard.dashboard_cards",
        "astra_core.ui.dashboard.dashboard_sidebar",
        "astra_core.ui.dashboard.dashboard_summary",
        "astra_core.ui.dashboard.dashboard_assistant",
    ]
    guardian.log("🧠 Guardian pre-launch verification started...")
    for mod in modules:
        try:
            importlib.import_module(mod)
            guardian.log(f"✅ Verified module: {mod}")
        except Exception as e:
            guardian.log(f"🚨 Failed to load {mod}: {e}")
    guardian.log("🧩 Guardian pre-launch verification complete.")
    return True


if __name__ == "__main__":
    run_guardian_prelaunch_check()
