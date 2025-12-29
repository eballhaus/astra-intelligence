import os, json, time, shutil

STATE_DEFENSE = "state/SENTINEL_DEFENSE_LOG.jsonl"
STATE_AUTOHEAL = "state/SENTINEL_AUTOHEAL_LOG.jsonl"
QUARANTINE_DIR = "_quarantine/autoheal_" + time.strftime("%Y%m%d_%H%M%S")

DEFAULT_EXCLUDES = [
    "__pycache__", ".git", ".idea", ".vscode", "venv", "tests", "docs",
    "archive", "backups", "legacy_backups", "core_backups", "_quarantine"
]

CLEAN_EXTENSIONS = [".pyc", ".bak", ".tmp", ".DS_Store"]
VALID_EXTENSIONS = (".py",)

def is_excluded(path: str) -> bool:
    lower = path.lower()
    return any(excl in lower for excl in DEFAULT_EXCLUDES)

def auto_clean_and_quarantine():
    actions = []
    os.makedirs(QUARANTINE_DIR, exist_ok=True)

    for root, _, files in os.walk("."):
        for f in files:
            fp = os.path.join(root, f)
            if is_excluded(fp):
                continue

            # Auto-delete junk
            if any(f.endswith(ext) for ext in CLEAN_EXTENSIONS):
                try:
                    os.remove(fp)
                    actions.append({"action": "deleted", "path": fp})
                except Exception as e:
                    actions.append({"action": "error_delete", "path": fp, "error": str(e)})
                continue

            # Auto-quarantine invalid .py files
            if f.endswith(".py") and (" 2" in f or f.count(".") > 2 or "backup" in f.lower()):
                try:
                    dest = os.path.join(QUARANTINE_DIR, os.path.relpath(fp, "."))
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.move(fp, dest)
                    actions.append({"action": "quarantined", "path": fp, "dest": dest})
                except Exception as e:
                    actions.append({"action": "error_quarantine", "path": fp, "error": str(e)})
    return actions

def run_defense():
    # Step 1: auto-heal
    healed = auto_clean_and_quarantine()

    # Step 2: basic validation scan
    violations = []
    for root, _, files in os.walk("."):
        for f in files:
            fp = os.path.join(root, f)
            if is_excluded(fp):
                continue
            if not f.endswith(VALID_EXTENSIONS):
                continue
            if " " in f or f.count(".") > 2:
                violations.append(fp)

    # Step 3: log results
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    os.makedirs("state", exist_ok=True)
    with open(STATE_DEFENSE, "a") as f:
        f.write(json.dumps({"timestamp": ts, "violations": violations}) + "\n")
    with open(STATE_AUTOHEAL, "a") as f:
        f.write(json.dumps({"timestamp": ts, "actions": healed}) + "\n")

    print("\n🛡️ ASTRA SENTINEL v4.2 — Auto-Heal Mode\n")
    print(f"🧹 Auto-clean actions: {len(healed)} logged to {STATE_AUTOHEAL}")
    if violations:
        print(f"🚨 Remaining structural issues: {len(violations)} (see {STATE_DEFENSE})")
    else:
        print("✅ Structure clean and stable. No remaining violations.")

if __name__ == "__main__":
    run_defense()
