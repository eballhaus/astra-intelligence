import os, json, shutil, time
LOCK_PATH = "state/audit_hashes.json"
BACKUP_ROOT = "legacy_backups/backups"

def monitor(interval=60):
    if not os.path.exists(LOCK_PATH):
        print("[RecoveryDaemon] No audit baseline found.")
        return
    with open(LOCK_PATH) as f:
        base = json.load(f)
    while True:
        for path, _ in base.items():
            if not os.path.exists(path):
                print(f"[RecoveryDaemon] ⚠️ Missing file {path}. Restoring...")
                candidates = [os.path.join(r, path.split("/")[-1]) for r,_,_ in os.walk(BACKUP_ROOT)]
                if candidates:
                    shutil.copy(candidates[0], path)
                    print(f"✅ Restored {path} from {candidates[0]}")
        time.sleep(interval)
