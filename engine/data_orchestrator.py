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

# --- Continue with normal imports ---
try:
    from core.guardian.guardian_v7 import guardian_log, GuardianV7
except ImportError:
    guardian_log = None
    GuardianV7 = None
    print("[Warning] GuardianV7 could not be imported. Live mode will be unavailable.")


# --- Main Function: fetch_live_data ---
def fetch_live_data():
    """
    Fetch live or mock data depending on configuration.
    When USE_LIVE_MODE = True, data will be pulled from GuardianV7 APIs.
    When False, returns stable mock data for testing.
    """
    USE_LIVE_MODE = True  # Toggle this flag as needed

    if not USE_LIVE_MODE:
        print("[Engine] Mock mode active — returning stub data.")
        return {
            "AAPL": {"price": 100.0, "timestamp": datetime.utcnow().isoformat()},
            "TSLA": {"price": 200.0, "timestamp": datetime.utcnow().isoformat()},
        }

    if USE_LIVE_MODE:
        if GuardianV7 is None:
            print("[Engine] Live mode selected, but GuardianV7 unavailable. Reverting to mock mode.")
            return {
                "AAPL": {"price": 100.0, "timestamp": datetime.utcnow().isoformat()},
                "TSLA": {"price": 200.0, "timestamp": datetime.utcnow().isoformat()},
            }

        print("[Engine] Live mode active — fetching from GuardianV7 APIs.")
        guardian = GuardianV7()
        try:
            live_data = guardian.fetch_live_data(symbols=["AAPL", "TSLA"])
            print("[Engine] Live data fetch successful.")
            return live_data
        except Exception as e:
            print(f"[Engine] Live fetch failed — using fallback. Error: {e}")

    # --- Fallback Mock Data ---
    print("[Engine] Using fallback mock dataset.")
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    mock = []
    for symbol in ["AAPL", "NVDA", "TSLA", "MSFT", "GOOG"]:
        mock.append({
            "symbol": symbol,
            "grade": random.choice(["A", "B", "C"]),
            "confidence": round(random.uniform(70, 99), 2),
            "price": round(random.uniform(100, 500), 2),
            "timestamp": now
        })
    return mock
