import sys, os; sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
# --- Astra Import Path Fix ---
import os
import sys
from datetime import datetime
import random

# Always resolve project root (one level up from 'engine')
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
core_path = os.path.join(project_root, 'core')

# Add these paths for this module’s context
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if core_path not in sys.path:
    sys.path.insert(0, core_path)

print(f"[DATA_ORCHESTRATOR FIX]")
print(f"  Project root: {project_root}")
print(f"  Core path: {core_path}")
print(f"  guardian_v7.py exists: {os.path.exists(os.path.join(core_path, 'guardian', 'guardian_v7.py'))}")

# --- GuardianV7 Import Fix ---
try:
    from guardian.guardian_v7 import GuardianV7
    print("[Engine] ✅ GuardianV7 imported successfully")
except ModuleNotFoundError as e:
    print("[Engine] ❌ GuardianV7 module missing:", e)
    GuardianV7 = None

# --- Continue with normal orchestrator logic ---

# --- Public helper for API bridge ---
def fetch_live_data(symbols=["AAPL", "TSLA"]):
    """Fetch live data via GuardianV7 (for API and dashboard use)."""
    if 'GuardianV7' not in globals() or GuardianV7 is None:
        raise RuntimeError("GuardianV7 not available; backend in fallback mode.")

    guardian = GuardianV7()
    try:
        data = guardian.fetch_live_data(symbols=symbols)
        return data
    except Exception as e:
        return {"error": f"Live data fetch failed: {e}"}
