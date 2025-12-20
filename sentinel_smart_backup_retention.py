#!/usr/bin/env python3
import os
from collections import defaultdict

TARGET_DIRS = ["engine", "core", "ui"]

backups = defaultdict(list)

# Collect all backup files
for root_dir in TARGET_DIRS:
    for root, _, files in os.walk(root_dir):
        for f in files:
            if f.endswith(".bak") or f.endswith(".sentinel.bak"):
                base_name = f.split(".")[0]  # e.g. data_orchestrator
                full_path = os.path.join(root, f)
                backups[os.path.join(root, base_name)].append(full_path)

# Retain only the newest per base file
deleted = 0
kept = 0
for base, paths in backups.items():
    if len(paths) > 1:
        paths.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        keep = paths[0]
        keep_time = os.path.getmtime(keep)
        kept += 1
        for p in paths[1:]:
            os.remove(p)
            deleted += 1
            print(f"[REMOVED] {p}")
        print(f"[KEPT] {keep} (latest backup for {base})")
    else:
        kept += 1

print(f"\n✅ Smart backup retention complete.")
print(f"🗂️ {kept} backups kept, 🧹 {deleted} old duplicates removed.")
