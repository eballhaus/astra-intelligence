"""
Integrity Builder – Astra Intelligence (Phase-90)
------------------------------------------------
Continuous integrity monitor for the Astra Intelligence framework.
Works with Guardian V6 to self-repair imports, modules, and file structures.
"""

import os
import sys
import json
import time
import importlib.util
from pathlib import Path
from datetime import datetime

# --- Fix Python path so "astra_modules" can be imported ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# ----------------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6


class IntegrityBuilder:
    def __init__(self, base_path: str = None):
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)
        self.repair_log = Path(self.base_path) / "astra_logs" / "integrity_repairs.log"
        self.required_paths = [
            "astra_modules/ui",
            "astra_modules/guardian",
            "astra_modules/universe",
            "astra_modules/chart_core",
            "astra_modules/system",
        ]

    # ----------------------------------------------------------------
    # Logging utilities
    # ----------------------------------------------------------------
    def _log(self, msg: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(self.repair_log.parent, exist_ok=True)
        with open(self.repair_log, "a") as f:
            f.write(f"[{ts}] {msg}\n")
        self.guardian._write_log(msg)

    # ----------------------------------------------------------------
    # Directory & file integrity
    # ----------------------------------------------------------------
    def verify_directories(self):
        """Ensure all required directories exist."""
        for rel in self.required_paths:
            path = Path(self.base_path) / rel
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                self._log(f"🧩 Re-created missing directory: {rel}")
            else:
                self._log(f"✅ Directory verified: {rel}")

    # ----------------------------------------------------------------
    # Import integrity
    # ----------------------------------------------------------------
    def verify_imports(self):
        """Attempt to import every Python module to detect broken imports."""
        checked = 0
        failed = 0
        modules_dir = Path(self.base_path) / "astra_modules"

        for pyfile in modules_dir.rglob("*.py"):
            if pyfile.name.startswith("__"):
                continue
            checked += 1
            try:
                spec = importlib.util.spec_from_file_location(pyfile.stem, pyfile)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)  # type: ignore
            except Exception as e:
                failed += 1
                self._log(f"⚠️ Import failure in {pyfile.relative_to(self.base_path)}: {e}")

        self._log(f"✅ Import scan complete: {checked} checked, {failed} failed")

    # ----------------------------------------------------------------
    # Run full system check
    # ----------------------------------------------------------------
    def run_full_integrity_check(self):
        """Run all integrity routines once."""
        self._log("🧠 Running full Astra integrity check...")
        self.verify_directories()
        self.verify_imports()
        self._log("✅ Integrity Builder phase complete.")

    # ----------------------------------------------------------------
    # Background repair loop (optional daemon)
    # ----------------------------------------------------------------
    def run_background_repair(self, interval=3600):
        """Run integrity verification every `interval` seconds."""
        while True:
            self.run_full_integrity_check()
            time.sleep(interval)


# --------------------------------------------------------------------
# Background watchdog entry point (used by Guardian)
# --------------------------------------------------------------------
def run_integrity_watchdog():
    """Called automatically by GuardianV6 to run background repairs."""
    ib = IntegrityBuilder(os.getcwd())
    ib.run_background_repair()


# --------------------------------------------------------------------
# Direct execution for manual testing
# --------------------------------------------------------------------
if __name__ == "__main__":
    ib = IntegrityBuilder(os.getcwd())
    ib.run_full_integrity_check()
    print("✅ Integrity Builder completed successfully.")

