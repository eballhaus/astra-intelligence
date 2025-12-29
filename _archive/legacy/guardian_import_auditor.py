"""
Guardian Import Auditor
----------------------------------------------------
Scans Guardian modules for import issues and verifies
integrity after initialization. Automatically logs results.
"""

import importlib
import json
from datetime import datetime

AUDIT_LOG_FILE = "guardian_import_audit.json"


def run_import_audit():
    """Run Guardian Import Audit and save summary to file."""
    print("🔍 Running Guardian Import Auditor...")

    results = []
    modules_to_check = [
        "core.guardian.guardian_core",
        "core.guardian.guardian_core",
        "core.guardian.guardian_core",
        "core.guardian.startup_hook",
    ]

    for mod_name in modules_to_check:
        try:
            importlib.import_module(mod_name)
            results.append({"module": mod_name, "status": "OK"})
        except (ImportError, OSError) as e:
            results.append({"module": mod_name, "status": f"ERROR: {e}"})

    audit_summary = {
        "timestamp": datetime.utcnow().isoformat(),
        "modules_checked": len(results),
        "results": results,
    }

    with open(encoding="utf-8", AUDIT_LOG_FILE, "w") as f:
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
