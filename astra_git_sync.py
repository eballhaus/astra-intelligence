#!/usr/bin/env python3
"""
Astra Intelligence — Git Sync Helper
-------------------------------------
Safely commits, backs up, and pushes your local work to GitHub.
Run manually or schedule with cron / macOS Automator.

Usage:
    python astra_git_sync.py
"""

import os
import subprocess
from datetime import datetime
from pathlib import Path
import shutil

# === CONFIGURATION ===
PROJECT_ROOT = Path(__file__).resolve().parent
BACKUP_DIR = PROJECT_ROOT / "backups"
BRANCH = "main"  # Change to 'dev' or 'staging' if needed


# === UTILITY FUNCTIONS ===
def run(cmd, check=True):
    """Run shell commands safely."""
    print(f"→ Running: {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout)
    if result.stderr.strip():
        print(result.stderr)
    if check and result.returncode != 0:
        raise RuntimeError(f"Command failed: {cmd}")
    return result


def ensure_git_repo():
    """Ensure we're inside a valid Git repository."""
    if not (PROJECT_ROOT / ".git").exists():
        print("🧩 Initializing new Git repository...")
        run("git init")
        run(f"git branch -M {BRANCH}")


def backup_changes():
    """Backup modified .py files with timestamps."""
    BACKUP_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_session = BACKUP_DIR / f"astra_backup_{timestamp}"
    backup_session.mkdir(parents=True, exist_ok=True)

    modified_files = (
        subprocess.run("git ls-files -m", shell=True, capture_output=True, text=True)
        .stdout.strip()
        .splitlines()
    )

    for file in modified_files:
        if file.endswith(".py"):
            dest = backup_session / Path(file).name
            shutil.copy(file, dest)
            print(f"🗂️  Backed up: {file} → {dest}")

    if modified_files:
        print(f"✅ Backup completed ({len(modified_files)} files).")
    else:
        print("✅ No modified files to back up.")


def sync_to_github():
    """Add, commit, and push all changes."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    run("git add .", check=False)

    try:
        run(f'git commit -m "Automated Astra Sync — {timestamp}"', check=False)
    except Exception:
        print("⚠️  Nothing new to commit.")

    try:
        run(f"git push origin {BRANCH}", check=False)
        print("🚀 Pushed successfully to GitHub.")
    except Exception:
        print("⚠️  Push failed — check remote or authentication.")


# === MAIN WORKFLOW ===
if __name__ == "__main__":
    print("🔄 Starting Astra Git Sync...")
    os.chdir(PROJECT_ROOT)
    ensure_git_repo()
    backup_changes()

    # Check if remote is configured
    remotes = subprocess.run(
        "git remote -v", shell=True, capture_output=True, text=True
    )
    if "origin" not in remotes.stdout:
        print("⚠️  No remote found. Add one with:")
        print("    git remote add origin <your_repo_url>")
    else:
        sync_to_github()

    print("✅ Astra Git Sync complete.")
