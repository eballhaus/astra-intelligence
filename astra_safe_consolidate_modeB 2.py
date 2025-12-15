#!/usr/bin/env python3
"""
Astra Intelligence v7.5 – Safe-Write Structural Consolidation (Mode B)
Performs backups, moves, merges, and import rewrites with full logging.
"""

import os, shutil, re, filecmp, difflib, subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ASTRA_MODULES = ROOT / "astra_modules"
ARCHIVE_ROOT = ROOT / "archive"
LOG_DIR = ROOT / "astra_logs"
LOG_DIR.mkdir(exist_ok=True)

BACKUP_DIR = ARCHIVE_ROOT / f"pre_migration_backup_{datetime.now():%Y%m%d_%H%M%S}"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

KEEP_FOLDERS = [
    "guardian", "engine", "fetch_core", "ui", "state", "agents",
    "forecast", "learning", "utils", "chart_core", "scanners", "core"
]

IMPORT_RULES = {
    r"from\s+astra_core\.": "from astra_modules.",
    r"from\s+astra_modules_legacy\.": "from astra_modules.",
    r"from\s+guardian\.guardian_v6": "from astra_modules.guardian.guardian_v7",
    r"from\s+utils\.safe_df": "from astra_modules.utils.safe_df",
    r"from\s+engine\.": "from astra_modules.engine.",
    r"from\s+fetch_core\.": "from astra_modules.fetch.",
    r"from\s+ui\.": "from astra_modules.ui."
}

# ------------------------------------------------------------
# UTILITIES
# ------------------------------------------------------------
def log(msg):
    print(msg)
    with open(LOG_DIR / "astra_migration_log.txt", "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def safe_copy(src: Path, dest: Path):
    """Copy directory tree safely."""
    if src.exists():
        log(f"📦 Backing up: {src} → {dest}")
        shutil.copytree(src, dest, dirs_exist_ok=True)

def move_folder(src: Path, dest: Path):
    """Move or merge folder contents."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        target = dest / rel
        if item.is_dir():
            target.mkdir(exist_ok=True)
        else:
            if target.exists():
                # keep the newer/larger file
                src_stat, tgt_stat = item.stat(), target.stat()
                if src_stat.st_mtime > tgt_stat.st_mtime or src_stat.st_size > tgt_stat.st_size:
                    shutil.copy2(item, target)
                    log(f"⚙️ Updated: {target}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    log(f"✅ Merged: {src} → {dest}")

def rewrite_imports(base: Path):
    """Rewrite imports safely within Python files."""
    for pyfile in base.rglob("*.py"):
        text = pyfile.read_text(encoding="utf-8", errors="ignore")
        new_text = text
        for old, new in IMPORT_RULES.items():
            new_text = re.sub(old, new, new_text)
        if new_text != text:
            with open(pyfile, "w", encoding="utf-8") as f:
                f.write(new_text)
            log(f"🔁 Imports rewritten in {pyfile}")

# ------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------
if __name__ == "__main__":
    log("🚀 Astra Intelligence v7.5 – Safe-Write Migration Starting")
    log(f"Backup folder: {BACKUP_DIR}")

    # 1️⃣ Back up everything first
    for folder in KEEP_FOLDERS:
        src = ROOT / folder
        if src.exists():
            safe_copy(src, BACKUP_DIR / folder)

    # 2️⃣ Move / merge into astra_modules
    for folder in KEEP_FOLDERS:
        src = ROOT / folder
        dest_name = "fetch" if folder == "fetch_core" else folder
        dest = ASTRA_MODULES / dest_name
        if src.exists():
            move_folder(src, dest)

    # 3️⃣ Rewrite imports
    rewrite_imports(ASTRA_MODULES)
    rewrite_imports(ROOT / "app.py")

    # 4️⃣ Archive deprecated layers
    for legacy in ["astra_core", "astra_modules_legacy", "guardian_old", "guardian_merge_review"]:
        src = ROOT / legacy
        if src.exists():
            target = ARCHIVE_ROOT / f"{legacy}_archived_{datetime.now():%Y%m%d}"
            shutil.move(str(src), str(target))
            log(f"🗃 Archived: {src} → {target}")

    # 5️⃣ Dependency validation
    log("🔍 Running Guardian diagnostics...")
    try:
        subprocess.run(
            ["python", "-m", "astra_modules.guardian.guardian_v7", "--diagnostics"],
            check=False,
        )
    except Exception as e:
        log(f"⚠️ Guardian diagnostics error: {e}")

    log("✅ Safe-Write Migration complete. See astra_migration_log.txt for details.")
