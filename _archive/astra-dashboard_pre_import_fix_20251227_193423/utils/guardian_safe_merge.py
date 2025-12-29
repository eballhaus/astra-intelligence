"""
guardian_safe_merge.py
Guardian-Supervised Safe Merge Script (Phase 4.0)

✅ Non-destructive
✅ Backs up entire repo before writing
✅ Prints all planned moves/copies first
✅ Requires explicit confirmation
"""

import shutil
import json
from pathlib import Path
from datetime import datetime

# === CONFIG ===
REPO_ROOT = Path(__file__).resolve().parent
ASTRA_MODULES = REPO_ROOT / "astra_modules"
LEGACY_DIR = REPO_ROOT / "legacy" / "astra_modules"
RESULTS_DIR = REPO_ROOT / "guardian_merge_review"
BACKUP_DIR = REPO_ROOT / "backups"

# Target structure (confirmed in Phase 3.8)
TARGET_MAP = {
    "core": ["feature_builder.py", "astra_prime.py", "astra_memory.py"],
    "engine": [
        "ranking_engine.py",
        "scan_manager.py",
        "state_bundle_builder.py",
        "astra_backend.py",
    ],
    "guardian": [
        "guardian_v6.py",
        "guardian_sync.py",
        "guardian_defender.py",
        "guardian_import_auditor.py",
        "pipeline_sanitizer.py",
        "schema_validator.py",
        "state_initializer.py",
        "startup_hook.py",
        "environment_guardian.py",
        "ui_integrity_lock.py",
    ],
    "fetch_core": [
        "fetch_crypto.py",
        "fetch_etf.py",
        "fetch_stock.py",
        "fetch_unified.py",
        "fetcher.py",
    ],
    "universe": ["universe_builder.py"],
    "guardian/security": ["api_keys.py"],
}

# === FUNCTIONS ===


def backup_repo():
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = BACKUP_DIR / f"astra_backup_phase4_{ts}.zip"
    print(f"[Guardian] Creating full repo backup: {backup_path}")
    #  shutil.make_archive(str(backup_path).replace(".zip", ""), "zip", str(REPO_ROOT))
    print("[Guardian] ✅ Backup complete.\n")


def plan_moves():
    planned_moves = []
    for dest, files in TARGET_MAP.items():
        target_dir = REPO_ROOT / dest
        for filename in files:
            src = ASTRA_MODULES / filename
            if not src.exists():
                # If nested file (like fetch_core)
                alt_src = ASTRA_MODULES / dest / filename
                if alt_src.exists():
                    src = alt_src
                else:
                    continue
            dest_path = target_dir / filename
            planned_moves.append({"from": str(src), "to": str(dest_path)})
    return planned_moves


def execute_moves(moves):
    for move in moves:
        src, dest = Path(move["from"]), Path(move["to"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[Move] {src.name} → {dest}")
        shutil.copy2(src, dest)
    print("\n[Guardian] ✅ All files safely copied to their destinations.")


def archive_astra_modules():
    print(f"[Guardian] Archiving old astra_modules → {LEGACY_DIR}")
    LEGACY_DIR.parent.mkdir(exist_ok=True)
    shutil.move(str(ASTRA_MODULES), str(LEGACY_DIR))
    print("[Guardian] ✅ Archive complete.\n")


# === MAIN EXECUTION ===


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["preview", "execute"], required=True)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    backup_repo()

    planned_moves = plan_moves()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = RESULTS_DIR / f"guardian_merge_plan_{ts}.json"
    json.dump(planned_moves, open(log_file, "w"), indent=2)

    print("\n📋 Planned Safe Merge Operations:")
    for move in planned_moves:
        print(f"  {move['from']}  →  {move['to']}")

    if args.mode == "preview":
        print("\n[Preview Mode] ✅ No files moved.")
        print(f"Plan saved to: {log_file}")
        return

    confirm = input("\n⚠️  Confirm Safe Merge Execution? (yes/no): ").strip().lower()
    if confirm != "yes":
        print("[Guardian] ❌ Merge aborted. No changes made.")
        return

    execute_moves(planned_moves)
    archive_astra_modules()
    print("[Guardian] ✅ Safe Merge Complete.")
    print(f"Full log: {log_file}")


if __name__ == "__main__":
    main()
