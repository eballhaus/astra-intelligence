"""
Guardian Import Auditor
----------------------------------------------------
Scans Guardian modules for import issues and verifies
integrity after initialization. Automatically logs results.
"""

import json
import os
from datetime import datetime
import importlib

AUDIT_LOG_FILE = "guardian_import_audit.json"


def run_import_audit():
    """Run Guardian Import Audit and save summary to file."""
    print("🔍 Running Guardian Import Auditor...")

    results = []
    modules_to_check = [
        "astra_modules.guardian.guardian_v4",
        "astra_modules.guardian.guardian_sentinel",
        "astra_modules.guardian.auto_repair",
        "astra_modules.guardian.startup_hook"
    ]

    for mod_name in modules_to_check:
        try:
            importlib.import_module(mod_name)
            results.append({"module": mod_name, "status": "OK"})
        except Exception as e:
            results.append({"module": mod_name, "status": f"ERROR: {e}"})

    audit_summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "modules_checked": len(results),
        "results": results
    }

    with open(AUDIT_LOG_FILE, "w") as f:
        json.dump(audit_summary, f, indent=2)

    print("\n🧩 Guardian Import Auditor Summary")
    print("--------------------------------------------------")
    for r in results:
        status = "✅" if r["status"] == "OK" else "❌"
        print(f"{status} {r['module']} — {r['status']}")
    print("--------------------------------------------------")
    print(f"✅ Audit complete. Report saved to {AUDIT_LOG_FILE}\n")

    return audit_summary


# Allow standalone CLI execution
if __name__ == "__main__":
    run_import_audit()
