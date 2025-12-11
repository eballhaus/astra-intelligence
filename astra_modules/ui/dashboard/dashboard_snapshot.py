"""
Dashboard Snapshot Manager
---------------------------
Creates automatic backups ("snapshots") of the Astra Dashboard layout before
any fix, auto-repair, or update is applied. Provides rollback utilities
for instant restoration of the last known good dashboard state.
"""

import datetime
import glob
import os
import zipfile

from astra_core.guardian import guardian_log

guardian = guardian_log()

# ============================================================
# 🗂️ CONFIG
# ============================================================

ROOT_DIR = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../../.."))
SNAPSHOT_DIR = os.path.join(ROOT_DIR, "astra_snapshots")
DASHBOARD_DIR = os.path.dirname(__file__)
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

MAX_SNAPSHOTS = 10  # Keep only the 10 most recent


# ============================================================
# 📦 CREATE SNAPSHOT
# ============================================================


def create_snapshot(tag: str = "auto"):
    """Create a zip snapshot of all dashboard files and contract."""
    try:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        zip_name = f"ui_dashboard_{timestamp}_{tag}.zip"
        zip_path = os.path.join(SNAPSHOT_DIR, zip_name)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file in glob.glob(os.path.join(DASHBOARD_DIR, "*.py")):
                zipf.write(file, arcname=os.path.basename(file))
            contract_path = os.path.join(
                DASHBOARD_DIR, "dashboard_contract.json")
            if os.path.exists(contract_path):
                zipf.write(contract_path, arcname="dashboard_contract.json")

        guardian.log(f"[Snapshot] 📦 Created dashboard snapshot: {zip_name}")
        _cleanup_old_snapshots()
        return zip_path
    except Exception as e:
        guardian.log(f"[Snapshot] ⚠️ Failed to create snapshot: {e}")
        return None


# ============================================================
# ♻️ ROLLBACK SNAPSHOT
# ============================================================


def rollback_to_latest():
    """Restore the latest snapshot if available."""
    try:
        zips = sorted(glob.glob(os.path.join(
            SNAPSHOT_DIR, "ui_dashboard_*.zip")))
        if not zips:
            guardian.log("[Snapshot] 🚫 No snapshots available for rollback.")
            return False

        latest = zips[-1]
        guardian.log(
            f"[Snapshot] ♻️ Restoring from: {os.path.basename(latest)}")

        with zipfile.ZipFile(latest, "r") as zipf:
            zipf.extractall(DASHBOARD_DIR)

        guardian.log("[Snapshot] ✅ Dashboard rollback completed successfully.")
        return True
    except Exception as e:
        guardian.log(f"[Snapshot] ❌ Rollback failed: {e}")
        return False


# ============================================================
# 🧹 SNAPSHOT CLEANUP
# ============================================================


def _cleanup_old_snapshots():
    """Keep only the newest N snapshots."""
    zips = sorted(glob.glob(os.path.join(SNAPSHOT_DIR, "ui_dashboard_*.zip")))
    if len(zips) > MAX_SNAPSHOTS:
        old = zips[:-MAX_SNAPSHOTS]
        for path in old:
            try:
                os.remove(path)
                guardian.log(
                    f"[Snapshot] 🗑️ Deleted old snapshot: {os.path.basename(path)}"
                )
            except Exception as e:
                guardian.log(f"[Snapshot] ⚠️ Failed to delete {path}: {e}")


# ============================================================
# 🚀 SELF-TEST
# ============================================================

if __name__ == "__main__":
    guardian.log("🧩 Dashboard Snapshot self-test starting...")
    create_snapshot("manual_test")
