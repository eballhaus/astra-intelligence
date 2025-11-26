"""
Guardian Sentinel Startup Hook (Improved Version)
----------------------------------------------------
Purpose:
- Run Guardian Sentinel integrity checks automatically
  before Astra Intelligence launches.
- Log results to Guardian's audit ledger.
- Print any import or runtime error cause clearly.

Run time: ~0.3–0.5 seconds
Impact: negligible
"""

import time
import importlib
import traceback
from datetime import datetime


def run_startup_check():
    """Run the Guardian Sentinel preflight check."""
    start_time = time.time()
    result = {"checked": 0, "failed": 0, "status": "unknown", "error": None}

    print("\n🔍 Starting Guardian Startup Check...\n")

    try:
        # Dynamically import Sentinel and Guardian
        try:
            sentinel_module = importlib.import_module("astra_modules.guardian.guardian_sentinel")
        except Exception as e:
            raise ImportError(f"Failed to import guardian_sentinel: {e}")

        try:
            guardian_module = importlib.import_module("astra_modules.guardian.guardian_v4")
        except Exception as e:
            raise ImportError(f"Failed to import guardian_v4: {e}")

        sentinel = getattr(sentinel_module, "sentinel", None)
        guardian = getattr(guardian_module, "guardian", None)

        if sentinel is None:
            raise RuntimeError("Sentinel instance not found.")
        if guardian is None:
            raise RuntimeError("Guardian instance not found.")

        # Run the Sentinel check
        result = sentinel.run()
        result["status"] = "ok" if result["failed"] == 0 else "warnings"

        # Log via Guardian’s audit system
        try:
            guardian.audit.record("startup_check", {
                "timestamp": datetime.utcnow().isoformat(),
                "modules_checked": result.get("checked", 0),
                "modules_failed": result.get("failed", 0),
                "status": result.get("status", "unknown")
            })
        except Exception as log_error:
            print(f"⚠️  Warning: Unable to log to Guardian audit: {log_error}")

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()

    result["duration"] = round(time.time() - start_time, 3)

    # Nicely formatted console report
    print("\n🛡️  Guardian Startup Check Complete")
    print("--------------------------------------------------")
    print(f"Status: {result['status']}")
    if result.get("error"):
        print(f"Error: {result['error']}")
        print("Traceback:")
        print(result['traceback'])
    print(f"Checked: {result.get('checked', '?')}, Failed: {result.get('failed', '?')}")
    print(f"Duration: {result['duration']}s")
    print("--------------------------------------------------\n")

    return result


# ==========================================================
# Auto-run if executed directly
# ==========================================================
if __name__ == "__main__":
    run_startup_check()
