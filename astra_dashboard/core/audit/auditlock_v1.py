import os, hashlib, json, time, pathlib

LOCK_PATH = "state/audit_hashes.json"
WATCH_DIRS = ["core", "learning", "engine", "ui", "guardian"]

def hash_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except:
        return None

def snapshot():
    state = {}
    for d in WATCH_DIRS:
        for root, _, files in os.walk(d):
            for file in files:
                if file.endswith(".py"):
                    fp = os.path.join(root, file)
                    state[fp] = hash_file(fp)
    os.makedirs("state", exist_ok=True)
    with open(LOCK_PATH, "w") as f:
        json.dump(state, f, indent=2)
    print(f"[AuditLock] Snapshot created with {len(state)} tracked files.")

def verify():
    if not os.path.exists(LOCK_PATH):
        print("[AuditLock] No baseline found. Run snapshot() first.")
        return
    with open(LOCK_PATH) as f:
        base = json.load(f)
    changed = []
    for path, old_hash in base.items():
        new_hash = hash_file(path)
        if new_hash != old_hash:
            changed.append(path)
    if changed:
        print("[AuditLock] ⚠️ Detected modified or corrupted files:")
        for c in changed:
            print("  -", c)
    else:
        print("[AuditLock] ✅ All tracked files unchanged.")
