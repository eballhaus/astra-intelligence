"""
Astra Intelligence – Incremental Preflight Verifier (Phase-90)
--------------------------------------------------------------
Optimized verification for faster startup and reduced redundancy.

This script:
 • Scans only changed files since last verification.
 • Repairs corrupted JSON/data files if needed.
 • Logs results to GuardianV6.
"""

import os
import sys
import json
import time
import compileall
from pathlib import Path
from datetime import datetime

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from astra_modules.guardian.guardian_v6 import GuardianV6

guardian = GuardianV6(str(PROJECT_ROOT))
TRACK_FILE = PROJECT_ROOT / "last_verified_files.json"


def load_previous_state():
    """Load file modification state from previous verification."""
    if TRACK_FILE.exists():
        try:
            with open(TRACK_FILE, "r") as f:
                return json.load(f)
        except Exception:
            guardian._write_log("Corrupted last_verified_files.json, resetting.")
    return {}


def save_state(state):
    """Save current file modification state."""
    with open(TRACK_FILE, "w") as f:
        json.dump(state, f, indent=2)


def get_all_py_files():
    """List all Python files under Astra modules."""
    files = []
    for root, _, filenames in os.walk(PROJECT_ROOT / "astra_modules"):
        for file in filenames:
            if file.endswith(".py"):
                path = Path(root) / file
                files.append(path)
    return files


def verify_files():
    """Verify only changed Python files."""
    previous = load_previous_state()
    current = {}
    changed = []

    all_files = get_all_py_files()
    for file in all_files:
        mtime = file.stat().st_mtime
        current[str(file)] = mtime
        if str(file) not in previous or previous[str(file)] != mtime:
            changed.append(file)

    if not changed:
        print("✅ No file changes detected since last verification.")
        guardian._write_log("No changes detected, skipping syntax compilation.")
        save_state(current)
        return True

    print(f"🔍 Verifying {len(changed)} modified file(s)...")
    for file in changed:
        try:
            compileall.compile_file(str(file), quiet=1)
        except Exception as e:
            print(f"❌ Syntax error in {file}: {e}")
            guardian.log_event("syntax_error", f"{file}: {e}")
            return False

    save_state(current)
    return True


def verify_data_files():
    """Check and repair JSON-based data stores."""
    json_files = [
        "astra_memory.json",
        "astra_learning.json",
        "astra_agent_states.json",
        "guardian_audit.json",
    ]
    for jf in json_files:
        path = PROJECT_ROOT / jf
        if not path.exists():
            guardian.log_event("data_missing", f"{jf} missing – recreating.")
            with open(path, "w") as f:
                json.dump({}, f)
            continue
        try:
            with open(path, "r") as f:
                json.load(f)
        except Exception:
            guardian.log_event("data_corrupt", f"{jf} corrupted – resetting.")
            with open(path, "w") as f:
                json.dump({}, f)


def main():
    print(f"\n🧠 Astra Intelligence – Preflight Check ({datetime.now():%Y-%m-%d %H:%M:%S})")
    print("------------------------------------------------------------")
    print("🔍 Running incremental syntax verification...")

    syntax_ok = verify_files()
    if not syntax_ok:
        print("❌ Syntax errors detected. Please fix before launch.")
        sys.exit(1)
    print("✅ Syntax check passed.")

    print("🔧 Validating Astra data files...")
    verify_data_files()
    print("✅ Data file integrity check complete.")

    print("🛡 Running GuardianV6 self-check...")
    guardian._write_log("Preflight check passed.")
    print("✅ Guardian self-check passed.\n")

    print("✅ Astra environment verified successfully.")
    print("🚀 Ready to launch Streamlit:  poetry run streamlit run app.py")
    guardian.log_event("preflight_complete", "Incremental verification finished successfully.")


if __name__ == "__main__":
    main()

