import os, json, time

SENTINEL_DEFENSE = "state/SENTINEL_DEFENSE_LOG.jsonl"
SENTINEL_AUTOHEAL = "state/SENTINEL_AUTOHEAL_LOG.jsonl"
GUARDIAN_VERIFY = "state/GUARDIAN_SELF_VERIFY_LOG.jsonl"

def read_last_entry(path):
    try:
        with open(path, "r") as f:
            lines = f.readlines()
            if not lines: return None
            return json.loads(lines[-1])
    except Exception:
        return None

def run_self_verification():
    defense = read_last_entry(SENTINEL_DEFENSE)
    heal = read_last_entry(SENTINEL_AUTOHEAL)

    if not defense:
        print("⚠️ No Sentinel defense log found.")
        return

    ts = defense.get("timestamp", "?")
    v_count = len(defense.get("violations", []))
    heal_actions = len(heal.get("actions", [])) if heal else 0

    status = "HEALTHY" if v_count == 0 else "CRITICAL"
    msg = {
        "timestamp": ts,
        "violations": v_count,
        "heal_actions": heal_actions,
        "status": status
    }

    os.makedirs("state", exist_ok=True)
    with open(GUARDIAN_VERIFY, "a") as f:
        f.write(json.dumps(msg) + "\n")

    print("\n🧩 ASTRA GUARDIAN LINK v3 — Self-Verification Mode\n")
    print(f"🕒 Last Sentinel scan: {ts}")
    print(f"🩺 Violations: {v_count} | Auto-heals: {heal_actions}")
    if status == "HEALTHY":
        print("✅ Guardian confirms stable integrity.")
    else:
        print("🚨 Guardian still reports unsafe structure!")

if __name__ == "__main__":
    run_self_verification()
