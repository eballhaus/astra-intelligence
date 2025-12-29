import os, json, time, threading
from datetime import datetime
from astra_dashboard.core.sentinel.sentinel_v1 import scan_repo, write_index, ASTRA_ROOT, INDEX_PATH

LOG_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_LOG.jsonl")
PREV_INDEX = os.path.join(ASTRA_ROOT, "state", "ASTRA_LIVE_INDEX_PREV.json")

SCAN_INTERVAL = 600  # seconds between background scans (10 min)

def compute_integrity_score(index):
    total_dupes = len(index.get("duplicates", []))
    subsystems = len(index.get("subsystems", {}))
    # Simple 0-100 scale where <50 dupes = perfect score
    base = max(0, 100 - (total_dupes / (subsystems + 1)))
    return round(min(100, base), 2)

def compare_indices(old, new):
    diffs = []
    if not old:
        return [{"type": "initial", "time": datetime.now().isoformat()}]
    for subsystem, data in new.get("subsystems", {}).items():
        if subsystem not in old.get("subsystems", {}):
            diffs.append({"type": "new_subsystem", "name": subsystem})
    if len(new.get("duplicates", [])) != len(old.get("duplicates", [])):
        diffs.append({"type": "dup_count_change",
                      "old": len(old.get("duplicates", [])),
                      "new": len(new.get("duplicates", []))})
    return diffs

def log_event(entry):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")

def run_scan():
    index = scan_repo(ASTRA_ROOT)
    write_index(index, INDEX_PATH)
    integrity = compute_integrity_score(index)

    old_index = None
    if os.path.exists(PREV_INDEX):
        with open(PREV_INDEX, "r") as f:
            old_index = json.load(f)
    diffs = compare_indices(old_index, index)

    entry = {
        "timestamp": datetime.now().isoformat(),
        "integrity_score": integrity,
        "duplicates": len(index.get("duplicates", [])),
        "changes": diffs
    }
    log_event(entry)
    with open(PREV_INDEX, "w") as f:
        json.dump(index, f, indent=2)

    print(f"🔄 Sentinel v2 scan complete — Integrity {integrity}% | Duplicates {len(index.get('duplicates', []))}")

def start_background_monitor():
    run_scan()
    threading.Timer(SCAN_INTERVAL, start_background_monitor).start()

if __name__ == "__main__":
    print("\\n🛰️  ASTRA SENTINEL v2 — Live Integrity Monitor\\n")
    start_background_monitor()
