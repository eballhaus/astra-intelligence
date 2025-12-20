#!/usr/bin/env python3
"""
Astra Cleanup Plan – Mode B++ (Safe-Write + Auto-Fix Imports)
──────────────────────────────────────────────────────────────
Non-destructive repository cleaner for Astra Intelligence.
• Moves backup/duplicate files to archive folders
• Compresses legacy and backup trees
• Auto-fixes imports if moved modules are referenced
• Runs Guardian / Sanity checks after each stage
• Full rollback available with  --rollback
"""

import os
import re
import sys
import tarfile
import shutil
import time
import ast
import subprocess
from pathlib import Path

SAFE_ROOT = Path(__file__).resolve().parents[1]
LOG_PATH = SAFE_ROOT / "astra_backups" / "cleanup_log.json"
ROLLBACK_PATH = SAFE_ROOT / "astra_backups" / "cleanup_safe"
os.makedirs(ROLLBACK_PATH, exist_ok=True)


def log(msg):
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(f"{time.ctime()}  {msg}\n")


def guardian_check():
    """Run guardian + sanity checks."""
    try:
        res = subprocess.run(
            [sys.executable, "astra_sanity_check.py"],
            cwd=SAFE_ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        ok = ("PASS" in res.stdout or "OK" in res.stdout) and res.returncode == 0
        log(f"[CHECK] Sanity {'OK' if ok else 'FAIL'}")
        if not ok:
            log(res.stdout)
        return ok
    except Exception as e:
        log(f"[ERROR] Guardian check failed: {e}")
        return False


def find_imports():
    """Return dict of imported modules → files using them."""
    mapping = {}
    for pyfile in SAFE_ROOT.rglob("*.py"):
        if "venv" in str(pyfile) or "backup" in str(pyfile):
            continue
        try:
            src = pyfile.read_text(errors="ignore")
            for node in ast.walk(ast.parse(src)):
                if isinstance(node, ast.Import):
                    for n in node.names:
                        mapping.setdefault(n.name.split(".")[0], []).append(str(pyfile))
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mapping.setdefault(node.module.split(".")[0], []).append(
                        str(pyfile)
                    )
        except Exception:
            continue
    return mapping


def safe_move(src: Path, dst: Path):
    """Move file safely with rollback copy."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    backup = ROLLBACK_PATH / src.relative_to(SAFE_ROOT)
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, backup)
    shutil.move(src, dst)
    log(f"[MOVE] {src}  →  {dst}")


def auto_fix_imports(old_name, new_pkg):
    """Update import lines referencing old_name."""
    pattern = re.compile(rf"(from\s+[\w\.]*{old_name}\s+import|import\s+{old_name})")
    for pyfile in SAFE_ROOT.rglob("*.py"):
        if "venv" in str(pyfile) or "backup" in str(pyfile):
            continue
        txt = pyfile.read_text(errors="ignore")
        if pattern.search(txt):
            newtxt = re.sub(
                rf"from\s+([\w\.]*){old_name}", rf"from {new_pkg}.{old_name}", txt
            )
            newtxt = re.sub(
                rf"import\s+{old_name}", rf"from {new_pkg} import {old_name}", newtxt
            )
            if newtxt != txt:
                pyfile.write_text(newtxt)
                log(f"[AUTO-FIX] Imports updated in {pyfile}")


def compress_dir(src: Path, target_name: str):
    tar_path = SAFE_ROOT / f"{target_name}.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(src, arcname=src.name)
    log(f"[ARCHIVE] {src} → {tar_path}")


def stage_guardian(mapping):
    guardian_dir = SAFE_ROOT / "guardian"
    archive_dir = guardian_dir / "backup_archive"
    archive_dir.mkdir(exist_ok=True)
    for f in guardian_dir.iterdir():
        if f.suffix == ".py" and ("copy" in f.stem or "bak" in f.name):
            if f.stem.split(".")[0] in mapping:
                log(f"[SKIP] {f} still imported.")
                continue
            safe_move(f, archive_dir / f.name)
            auto_fix_imports(f.stem.split(".")[0], "guardian.backup_archive")
    return guardian_check()


def stage_ui(mapping):
    ui_dash = SAFE_ROOT / "ui" / "dashboard"
    archive_dir = SAFE_ROOT / "ui" / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    for f in ui_dash.glob("tab_dashboard_*.py"):
        if f.stem.split(".")[0] in mapping:
            log(f"[SKIP] {f} still imported.")
            continue
        safe_move(f, archive_dir / f.name)
        auto_fix_imports(f.stem.split(".")[0], "ui.archive")
    return guardian_check()


def stage_legacy():
    legacy = SAFE_ROOT / "legacy"
    backups = SAFE_ROOT / "astra_backups"
    if legacy.exists():
        compress_dir(legacy, "legacy_archive_2025Q4")
    if backups.exists():
        compress_dir(backups, "astra_backups_archive_2025Q4")
    return guardian_check()


def clean_pycache():
    for d in SAFE_ROOT.rglob("__pycache__"):
        try:
            shutil.rmtree(d)
            log(f"[DEL] {d}")
        except Exception:
            continue


def rollback():
    if not ROLLBACK_PATH.exists():
        print("No rollback data found.")
        return
    for f in ROLLBACK_PATH.rglob("*"):
        if f.is_file():
            dest = SAFE_ROOT / f.relative_to(ROLLBACK_PATH)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, dest)
            log(f"[ROLLBACK] {f} → {dest}")
    print("Rollback complete. Review repo and rerun Guardian checks.")


def main():
    if "--rollback" in sys.argv:
        rollback()
        return

    log("=== ASTRA CLEANUP PLAN • MODE B++ ===")
    mapping = find_imports()
    log(f"[SCAN] {len(mapping)} top-level imports mapped.")

    if input("Proceed with Guardian cleanup? [y/n]: ").lower() == "y":
        if not stage_guardian(mapping):
            print("Guardian cleanup aborted.")
            return

    if input("Proceed with UI cleanup? [y/n]: ").lower() == "y":
        if not stage_ui(mapping):
            print("UI cleanup aborted.")
            return

    if input("Proceed with legacy/archive compression? [y/n]: ").lower() == "y":
        stage_legacy()

    if input("Remove __pycache__ dirs? [y/n]: ").lower() == "y":
        clean_pycache()

    log("Cleanup complete.")
    guardian_check()
    log("Summary log: " + str(LOG_PATH))


if __name__ == "__main__":
    main()
