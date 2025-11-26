"""
GuardianV6 – Astra Intelligence (Phase-90)
------------------------------------------
Primary self-defense and orchestration layer for Astra Intelligence.
Handles logging, verification, checkpoints, and automatic recovery.
"""

import os
import json
import time
import shutil
import subprocess
import threading
from datetime import datetime
from pathlib import Path


class GuardianV6:
    def __init__(self, base_path: str = None):
        self.base_path = base_path or os.getcwd()
        self.log_file = Path(self.base_path) / "guardian_v6.log"

        self._write_log("GuardianV6 initialized.")
        print("🛡️ Guardian V6 initialized successfully.")
        print("✅ Guardian package initialized (Phase-90 / V6).")

        # lightweight verification reminder
        check_last_verification()

        # create checkpoint snapshot
        self.create_checkpoint()

    # ----------------------------------------------------------------
    # Logging utilities
    # ----------------------------------------------------------------
    def _write_log(self, message: str):
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            with open(self.log_file, "a") as f:
                f.write(f"[{ts}] {message}\n")
        except Exception:
            print(f"[{ts}] {message}")

    def log_event(self, tag: str, details: str):
        self._write_log(f"[{tag.upper()}] {details}")

    # ----------------------------------------------------------------
    # Safe execution wrapper
    # ----------------------------------------------------------------
    def safe_run(self, func):
        """Executes a callable safely and logs any exception."""
        try:
            func()
            self._write_log("✅ safe_run executed successfully.")
        except Exception as e:
            self._write_log(f"❌ safe_run encountered an error: {e}")
            print(f"GuardianV6 caught an error during safe_run: {e}")

    # ----------------------------------------------------------------
    # Preflight verifier (manual / on-demand)
    # ----------------------------------------------------------------
    def auto_verify(self):
        """Run verify_astra.py with extended timeout."""
        verify_script = Path(self.base_path) / "verify_astra.py"
        if not verify_script.exists():
            self._write_log("verify_astra.py not found – skipping preflight.")
            return

        try:
            result = subprocess.run(
                ["python", str(verify_script)],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                self._write_log("✅ Preflight verification successful.")
            else:
                self._write_log(
                    f"❌ Preflight failed:\n{result.stdout}\n{result.stderr}"
                )
        except subprocess.TimeoutExpired:
            self._write_log("Verification timed out after 300 s.")
        except Exception as e:
            self._write_log(f"Verification error: {e}")

    # ----------------------------------------------------------------
    # Checkpoint snapshot
    # ----------------------------------------------------------------
    def create_checkpoint(self):
        """Create a backup snapshot of astra_modules."""
        try:
            modules_dir = Path(self.base_path) / "astra_modules"
            if not modules_dir.exists():
                return
            backup_dir = Path(self.base_path) / "astra_backup_cache"
            backup_dir.mkdir(exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = backup_dir / f"modules_backup_{timestamp}"
            shutil.copytree(modules_dir, target, dirs_exist_ok=True)
            self._write_log(f"🧠 Checkpoint created: {target}")
        except Exception as e:
            self._write_log(f"⚠️ Failed to create checkpoint: {e}")

    # ----------------------------------------------------------------
    # Auto-recovery
    # ----------------------------------------------------------------
    def recover_last_stable(self):
        """Recover Astra from the last known stable state."""
        try:
            stable_path = Path(self.base_path) / "astra_backup_cache"
            target_path = Path(self.base_path) / "astra_modules"
            if not stable_path.exists():
                print("⚠️ No stable backup found for recovery.")
                return
            latest = sorted(stable_path.glob("modules_backup_*"))[-1]
            shutil.copytree(latest, target_path, dirs_exist_ok=True)
            self._write_log("✅ Recovered Astra from stable backup.")
            print("✅ Astra restored to last known good state.")
        except Exception as e:
            self._write_log(f"❌ Recovery failed: {e}")

# --------------------------------------------------------------------
# Lightweight verification reminder (Phase-90)
# --------------------------------------------------------------------
def check_last_verification():
    """Prints a warning if files changed since last verified run."""
    import json, os
    from pathlib import Path
    try:
        project_root = Path(__file__).resolve().parents[2]
        tracker = project_root / "last_verified_files.json"
        if not tracker.exists():
            print("⚠️ No verification tracker found. Run verify_astra.py once.")
            return

        with open(tracker, "r") as f:
            last_state = json.load(f)

        if not isinstance(last_state, dict) or len(last_state) < 5:
            print("⚠️ Tracker file incomplete. Run verify_astra.py again.")
            return

        changed = []
        for path_str, mtime in last_state.items():
            p = Path(path_str)
            if p.exists() and os.path.getmtime(p) > mtime:
                changed.append(p.name)

        if changed:
            print(f"⚠️ {len(changed)} file(s) modified since last verification.")
            print("   Run `poetry run python verify_astra.py` for a full check.")
        else:
            print("✅ Codebase unchanged since last verification.")
    except Exception as e:
        print(f"⚠️ Lightweight verification check failed: {e}")
# --------------------------------------------------------------------
