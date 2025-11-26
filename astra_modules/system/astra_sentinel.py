"""
Astra Stability Sentinel – Phase-101
------------------------------------
Boot-time watchdog ensuring Guardian V6 is active, verified, and healthy.
"""

import os
import sys
import json
import time
import subprocess
from datetime import datetime

# --- Ensure project root on sys.path ---
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from astra_modules.guardian.guardian_v6 import GuardianV6


class AstraStabilitySentinel:
    def __init__(self, base_path):
        self.base_path = base_path
        self.report_file = os.path.join(base_path, "sentinel_report.json")
        self.guardian = None
        self._write_log("🛰️ Sentinel boot sequence initialized.")

    # -------------------------------------------------------------
    # Core logic
    # -------------------------------------------------------------

    def _write_log(self, msg):
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        print(f"{timestamp} {msg}")

    def launch_guardian(self):
        """Start or verify Guardian V6."""
        try:
            self.guardian = GuardianV6(self.base_path)
            self._write_log("✅ Guardian V6 launched and verified.")
            return True
        except Exception as e:
            self._write_log(f"❌ Guardian launch failed: {e}")
            return False

    def verify_environment(self):
        """Run verify_astra.py quietly."""
        self._write_log("🧠 Running boot-time environment verification...")
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(self.base_path, "verify_astra.py")],
                capture_output=True,
                text=True,
                timeout=60,
            )
            ok = result.returncode == 0
            summary = {
                "timestamp": datetime.now().isoformat(),
                "verified": ok,
                "output": result.stdout[-400:],
            }
            with open(self.report_file, "w") as f:
                json.dump(summary, f, indent=2)
            if ok:
                self._write_log("✅ Boot verification passed.")
            else:
                self._write_log("⚠️ Boot verification reported issues.")
        except Exception as e:
            self._write_log(f"❌ Sentinel verification error: {e}")

    def run_monitor_loop(self):
        """Lightweight loop to keep Guardian alive."""
        self._write_log("💠 Sentinel monitor loop active.")
        while True:
            try:
                # Simple heartbeat check
                if not getattr(self.guardian, "running", False):
                    self._write_log("⚠️ Guardian inactive – restarting...")
                    self.launch_guardian()
                time.sleep(120)
            except KeyboardInterrupt:
                self._write_log("🛑 Sentinel shutting down by user.")
                break
            except Exception as e:
                self._write_log(f"⚠️ Sentinel caught runtime error: {e}")


# -------------------------------------------------------------
# Main entry point
# -------------------------------------------------------------
if __name__ == "__main__":
    base_path = os.getcwd()
    sentinel = AstraStabilitySentinel(base_path)

    if sentinel.launch_guardian():
        sentinel.verify_environment()
        sentinel.run_monitor_loop()

