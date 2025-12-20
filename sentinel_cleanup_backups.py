#!/usr/bin/env python3
import os, time

TARGET_DIRS = ["engine", "core", "ui"]
MAX_AGE_DAYS = 7

now = time.time()
cutoff = now - (MAX_AGE_DAYS * 86400)

def is_old_backup(path):
    return (path.endswith(".bak") or path.endswith(".sentinel.bak")) and os.path.getmtime(path) < cutoff

deleted = 0
for root_dir in TARGET_DIRS:
    for root, _, files in os.walk(root_dir):
        for f in files:
            full = os.path.join(root, f)
            if is_old_backup(full):
                os.remove(full)
                deleted += 1
                print(f"[REMOVED] {full}")

print(f"\n✅ Sentinel backup cleanup complete. {deleted} old backups removed.")
