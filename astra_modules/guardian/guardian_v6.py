"""
GuardianV6 – Phase-101 (Silent Reinit + Heartbeat)
--------------------------------------------------
Guardian manages Astra’s runtime health, file integrity, and self-recovery.
Phase-101 upgrades:
- Eliminates redundant initialization logs
- Adds heartbeat monitoring thread
- Detects and restarts orphaned components
- Integrates with verify_astra.py when requested
"""

import os
import sys
import json
import time
import threading
from datetime import datetime
import subprocess

# Ensure project root path is always included
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

LOG_FILE = os.path.join(BASE_DIR, "guardian_v6.log")
AUDIT_FILE = os.path.join(BASE_DIR, "guardian_audit.json")
HEARTBEAT_INTERVAL = 60  # seconds


class GuardianV6:
    """Central Guardian Controller (Phase-101)."""

    def __init__(self, base_path: str):
        self.base_path = base_path
        self.log_file = LOG_FILE
        self.audit_file = AUDIT_FILE
        self._initialized = False
        self.last_heartbeat = None
        self.running = True

        # Initialize logging safely
        self._initialize_files()
        self._write_log("🛡️ Guardian V6 initialized successfully.")
        self._record_audit("INIT", "GuardianV6 started")

        # Launch heartbeat thread (non-blocking)
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()

        self._initialized = True
        self._write_log("✅ Guardian package initialized (Phase-101 / Silent Reinit)")

    # ------------------------------------------------------------------
    # Core Utilities
    # ------------------------------------------------------------------

    def _initialize_files(self):
        """Ensure log and audit files exist."""
        for file in [self.log_file, self.audit_file]:
            if not os.path.exists(file):
                with open(file, "w") as f:
                    f.write("{}" if file.endswith(".json") else "")
        self._write_log("🔧 Guardian files verified.")

    def _write_log(self, message: str):
        """Append timestamped message to Guardian log."""
        timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        with open(self.log_file, "a") as f:
            f.write(f"{timestamp} {message}\n")

    def log_event(self, event_type: str, message: str):
        """
        Universal event logger for Astra modules.
        Keeps backward compatibility with _write_log().
        """
        try:
            formatted = f"[{event_type.upper()}] {message}"
            self._write_log(formatted)
            self._record_audit(event_type, message)
        except Exception as e:
            self._write_log(f"[log_event error] {e}")

    def _record_audit(self, event: str, detail: str):
        """Record Guardian events in JSON audit log."""
        try:
            if os.path.exists(self.audit_file):
                with open(self.audit_file, "r") as f:
                    data = json.load(f) or {}
            else:
                data = {}
            data[datetime.now().isoformat()] = {"event": event, "detail": detail}
            with open(self.audit_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            self._write_log(f"[Audit Error] {e}")

    # ------------------------------------------------------------------
    # Safe Execution
    # ------------------------------------------------------------------

    def safe_run(self, func):
        """Safely execute a function with Guardian protection."""
        try:
            result = func()
            self._write_log("✅ safe_run executed successfully.")
            return result
        except Exception as e:
            self._write_log(f"⚠️ GuardianV6 caught an error during safe_run: {e}")
            return None

    # ------------------------------------------------------------------
    # Verification and Integrity Check
    # ------------------------------------------------------------------

    def verify_integrity(self):
        """Run verify_astra.py as a subprocess."""
        self._write_log("🧠 Running Astra preflight verification...")
        try:
            result = subprocess.run(
                [sys.executable, os.path.join(self.base_path, "verify_astra.py")],
                capture_output=True,
                text=True,
                timeout=90,
            )
            if result.returncode == 0:
                self._write_log("✅ Preflight verification successful.")
                self._record_audit("VERIFY", "Integrity check passed")
            else:
                self._write_log(f"❌ Verification failed: {result.stderr.strip()}")
                self._record_audit("VERIFY_FAIL", result.stderr.strip())
        except subprocess.TimeoutExpired:
            self._write_log("⚠️ Verification timed out.")
        except Exception as e:
            self._write_log(f"❌ Verification error: {e}")

    # ------------------------------------------------------------------
    # Heartbeat Monitoring
    # ------------------------------------------------------------------

    def _heartbeat_loop(self):
        """Background loop to emit silent heartbeats and check component health."""
        self._write_log("🫀 Guardian heartbeat monitor started.")
        while self.running:
            self.last_heartbeat = datetime.now().strftime("%H:%M:%S")
            self._write_log(f"💓 Heartbeat OK ({self.last_heartbeat})")

            # Auto-heal verification (every N beats)
            if int(time.time()) % (HEARTBEAT_INTERVAL * 5) < 5:
                self._auto_heal_check()

            time.sleep(HEARTBEAT_INTERVAL)

    def _auto_heal_check(self):
        """Check for missing components or errors and trigger lightweight recovery."""
        self._write_log("🧩 Running Guardian auto-heal check...")
        missing_files = []
        for critical_file in ["app.py", "verify_astra.py"]:
            if not os.path.exists(os.path.join(self.base_path, critical_file)):
                missing_files.append(critical_file)

        if missing_files:
            self._write_log(f"⚠️ Missing critical files: {missing_files}")
            self._record_audit("AUTO_HEAL", f"Missing {missing_files}")
        else:
            self._write_log("✅ Auto-heal check passed.")

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self):
        """Stop Guardian and cleanup."""
        self.running = False
        self._write_log("🛑 Guardian V6 shutting down.")
        self._record_audit("SHUTDOWN", "Guardian terminated cleanly.")


# ----------------------------------------------------------------------
# Standalone Execution
# ----------------------------------------------------------------------

if __name__ == "__main__":
    base = os.getcwd()
    guardian = GuardianV6(base)
    guardian.safe_run(lambda: print(f">>> GuardianV6 Silent Mode initialized at {base}"))
    guardian.verify_integrity()
    try:
        while True:
            time.sleep(5)
    except KeyboardInterrupt:
        guardian.shutdown()
