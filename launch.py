"""
launch.py — Astra Intelligence Entry Point
------------------------------------------
Enhanced with Guardian Phase-100 stack:
- AutoRepair
- Startup Validation
- Import Auditor
Runs automatically on launch with minimal performance impact.
"""

import json
from datetime import datetime

# ==========================================================
# Phase-100 Guardian Boot Sequence
# ==========================================================
print("\n🔧 Initializing Astra Guardian Stack...")

try:
    from astra_core.guardian.auto_repair import GuardianAutoRepair
    from astra_core.guardian.startup_hook import run_startup_check
    from astra_core.guardian.guardian_import_auditor import run_import_audit

    # Silent Auto-Repair
    repair = GuardianAutoRepair()
    repair_summary = repair.run()

    # Silent Startup Validation
    startup_summary = run_startup_check()

    # Optional: Run Import Auditor (logs to JSON)
    run_import_audit()

    print("\n🧩 Guardian Phase-100 Boot Summary")
    print("--------------------------------------------------")
    print(
        json.dumps(
            {
                "auto_repair": repair_summary if repair_summary else "OK",
                "startup_check": startup_summary if startup_summary else "OK",
                "timestamp": datetime.utcnow().isoformat(),
            },
            indent=2,
        )
    )
    print("--------------------------------------------------\n")

except Exception as e:
    print(f"⚠️ Guardian boot sequence encountered an issue: {e}")

# ==========================================================
# Launch Astra Intelligence (Streamlit UI)
# ==========================================================
print("🚀 Launching Astra Intelligence Dashboard...")

try:
    import streamlit.web.cli as stcli
    import sys

    # Run Streamlit in process
    sys.argv = ["streamlit", "run", "app.py"]
    sys.exit(stcli.main())

except Exception as e:
    print(f"❌ Failed to launch Streamlit dashboard: {e}")
