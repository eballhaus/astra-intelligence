"""
Guardian UI Integrity Lock
Runs lightweight verification of Astra's UI and repo integrity.
Non-blocking; logs to guardian/logs/ui_integrity.log
"""

import datetime
import os
import subprocess
import threading

LOG_PATH = "guardian/logs/ui_integrity.log"
REQUIRED_GITIGNORE_RULES = [
    "astra_backup_cache/modules_backup_*",
    "astra_cache/",
    "astra_modules/ui/theme_DEPRECATED/",
    "astra_modules/_legacy_backup/",
    "**/__pycache__/",
    "*.pyc",
    ".DS_Store",
]


def log(msg: str):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(f"[{datetime.datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")


def check_git_sync():
    try:
        local = subprocess.check_output(["git", "rev-parse", "HEAD"]).strip()
        remote = subprocess.check_output(
            ["git", "rev-parse", "origin/main"]).strip()
        if local != remote:
            log(f"⚠️  Git mismatch: local {local[:7]} vs remote {remote[:7]}")
        else:
            log("✅ Git HEAD matches origin/main")
    except Exception as e:
        log(f"⚠️  Git check failed: {e}")


def check_structure():
    bad_paths = []
    for root, dirs, _ in os.walk("."):
        for d in dirs:
            if "modules_backup_" in d or d in ["theme_DEPRECATED", "_legacy_backup"]:
                bad_paths.append(os.path.join(root, d))
    if bad_paths:
        log(f"⚠️  Unexpected legacy folders: {bad_paths}")
    else:
        log("✅ No legacy or backup folders found")


def check_ui_theme():
    themes = []
    for root, _, files in os.walk("astra_modules/ui"):
        for f in files:
            if f.startswith("astra_theme") and f.endswith(".css"):
                themes.append(os.path.join(root, f))
    if len(themes) == 1:
        log(f"✅ Single active theme: {themes[0]}")
    elif len(themes) > 1:
        log(f"⚠️  Multiple themes detected: {themes}")
    else:
        log("⚠️  No theme found under astra_modules/ui")


def check_gitignore():
    try:
        with open(".gitignore") as f:
            content = f.read()
        missing = [r for r in REQUIRED_GITIGNORE_RULES if r not in content]
        if missing:
            log(f"⚠️  Missing .gitignore rules: {missing}")
        else:
            log("✅ .gitignore integrity confirmed")
    except FileNotFoundError:
        log("⚠️  .gitignore not found")


def run_all_checks():
    log("---- Astra Guardian Integrity Check Start ----")
    for check in [check_structure, check_ui_theme, check_gitignore, check_git_sync]:
        try:
            check()
        except Exception as e:
            log(f"⚠️  Check error: {e}")
    log("---- Astra Guardian Integrity Check Complete ----\n")


def start_background_check():
    thread = threading.Thread(target=run_all_checks, daemon=True)
    thread.start()


if __name__ == "__main__":
    start_background_check()
