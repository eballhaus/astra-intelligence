import json, os, time

STATE_FILE = "state/SENTINEL_DEFENSE_LOG.jsonl"

DEFAULT_EXCLUDES = [
    "__pycache__", ".pyc", ".bak", ".tmp", ".DS_Store",
    "_quarantine", "archive", "backups", "legacy_backups", "core_backups",
    ".git", ".idea", ".vscode", "venv", "tests", "docs"
]

VALID_EXTENSIONS = (".py",)  # Only Python source files trigger analysis

def is_excluded(path: str) -> bool:
    lower = path.lower()
    return any(excl in lower for excl in DEFAULT_EXCLUDES)

def run_defense():
    violations = []
    for root, _, files in os.walk("."):
        for f in files:
            fp = os.path.join(root, f)
            if is_excluded(fp):
                continue
            if not f.endswith(VALID_EXTENSIONS):
                continue
            # Example check: filenames with spaces or strange suffixes
            if " " in f or f.count(".") > 2:
                violations.append(fp)

    result = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "violations": violations
    }

    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "a") as log:
        log.write(json.dumps(result) + "\n")

    print("\n🛡️ ASTRA SENTINEL v4.1 — Pattern-Aware Defense (Refined)\n")
    if violations:
        print(f"🚨 {len(violations)} real structural issues detected! Logged in {STATE_FILE}")
    else:
        print("✅ No structural policy violations detected.")

if __name__ == "__main__":
    run_defense()
