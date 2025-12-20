"""
Guardian Sentinel – Astra Integrity Watcher
----------------------------------------------------
Purpose:
- Verify that all Astra modules load cleanly at startup
- Detect broken or corrupted files before runtime
- Automatically restore or quarantine failed modules
- Log all issues in GuardianV4’s audit system

Phase: 90 → 100 bridge (lightweight, zero-latency impact)
"""

import hashlib
import importlib
import json
import os
import traceback
from datetime import datetime

# Link with GuardianV4’s logger if available
try:
    from core.guardian.guardian_v7 import guardian
except Exception:
    guardian = None


class GuardianSentinel:
    """Runs quick integrity checks before Astra boots."""

    def __init__(self, base_path=None, modules_to_check=None):
        self.base_path = base_path or os.getcwd()
        self.modules_to_check = modules_to_check or [
            "core.guardian.guardian_v7",
            "core.guardian.environment_guardian",
            "core.guardian",
            "core.agents",
            "core.core",
        ]
        self.log_path = os.path.join(self.base_path, "sentinel_report.json")
        self.report = {"checked": [], "failed": [], "repaired": [], "timestamp": None}

    # ==========================================================
    # Core Check Functions
    # ==========================================================
    def hash_file(self, path):
        """Generate SHA256 hash for file."""
        try:
            with open(path, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
        except Exception:
            return None

    def check_imports(self):
        """Attempt to import core modules to verify syntax and integrity."""
        for mod_name in self.modules_to_check:
            try:
                importlib.import_module(mod_name)
                self.report["checked"].append(mod_name)
            except Exception as e:
                self.report["failed"].append(
                    {
                        "module": mod_name,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    }
                )

    def verify_file_hashes(self):
        """Cross-check hashes of known key modules with Guardian audit log."""
        ledger_file = os.path.join(self.base_path, "guardian_audit.json")
        if not os.path.exists(ledger_file):
            return  # nothing to compare yet

        try:
            with open(ledger_file, "r") as f:
                data = json.load(f)
            events = data.get("events", [])
        except Exception:
            return

        logged_hashes = {
            e["payload"].get("file"): e["payload"].get("hash")
            for e in events
            if e["type"] == "file_integrity"
        }

        for file_path, logged_hash in logged_hashes.items():
            abs_path = os.path.join(self.base_path, file_path)
            if os.path.exists(abs_path):
                current_hash = self.hash_file(abs_path)
                if logged_hash and current_hash != logged_hash:
                    self.report["failed"].append(
                        {
                            "module": file_path,
                            "error": "Hash mismatch — possible corruption.",
                        }
                    )

    def repair_or_quarantine(self):
        """Placeholder for future auto-restore feature (Phase-100)."""
        # For now, this just logs the failure into Guardian’s audit ledger
        for failed in self.report["failed"]:
            if guardian:
                guardian.audit.record("integrity_alert", failed)

    # ==========================================================
    # Sentinel Runner
    # ==========================================================
    def run(self):
        """Execute all checks and save a report."""
        self.report["timestamp"] = datetime.utcnow().isoformat()
        self.check_imports()
        self.verify_file_hashes()
        self.repair_or_quarantine()

        # Save sentinel results
        with open(self.log_path, "w") as f:
            json.dump(self.report, f, indent=2)

        # Log to Guardian if available
        if guardian:
            guardian.audit.record(
                "sentinel_report",
                {
                    "checked": len(self.report["checked"]),
                    "failed": len(self.report["failed"]),
                    "timestamp": self.report["timestamp"],
                },
            )

        # Return summary
        return {
            "checked": len(self.report["checked"]),
            "failed": len(self.report["failed"]),
            "report_file": self.log_path,
        }


# ==========================================================
# Singleton Runner for startup
# ==========================================================
sentinel = GuardianSentinel()

if __name__ == "__main__":
    result = sentinel.run()
    print("\n🛡️  Guardian Sentinel Startup Report")
    print("--------------------------------------------------")
    print(json.dumps(result, indent=2))
    print("--------------------------------------------------\n")
