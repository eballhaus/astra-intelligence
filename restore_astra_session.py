"""
Astra Session Restore Script
----------------------------------------------------
Purpose:
    - Reconnects ChatGPT or developer to the exact state of Astra.
    - Verifies Guardian stack health and prints the current phase.
Usage:
    (venv) python restore_astra_session.py
"""

import os
import json
from datetime import datetime
from astra_modules.guardian.guardian_v4 import guardian
from astra_modules.guardian.auto_repair import GuardianAutoRepair
from astra_modules.guardian.startup_hook import run_startup_check
from astra_modules.guardian.guardian_sync import GuardianSync

CHECKPOINT_FILE = "astra_phase_checkpoint.json"


def load_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return {"current_phase": "Unknown", "next": "Unknown"}


def run_restore():
    print("\n🔄 Astra Session Restore")
    print("--------------------------------------------------")

    checkpoint = load_checkpoint()
    print(f"🧭 Current Phase: {checkpoint['current_phase']}")
    print(f"➡️  Next Planned Step: {checkpoint['next']}")

    # Run quick system validation
    print("\n🧩 Running Guardian Auto-Repair...")
    GuardianAutoRepair().run()

    print("\n🛡️ Running Guardian Startup Hook...")
    run_startup_check()

    print("\n🔐 Running GuardianSync...")
    GuardianSync().run()

    print("\n✅ Astra Environment Ready.")
    print(f"Timestamp: {datetime.utcnow().isoformat()}")
    print("--------------------------------------------------\n")


if __name__ == "__main__":
    run_restore()
