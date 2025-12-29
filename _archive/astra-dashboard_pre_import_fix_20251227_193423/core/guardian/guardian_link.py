import os, json, time
from datetime import datetime

ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
TREND_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_TRENDS.json")
DEFENSE_LOG = os.path.join(ASTRA_ROOT, "state", "SENTINEL_DEFENSE_LOG.jsonl")
HOOK_LOG = os.path.join(ASTRA_ROOT, "state", "SENTINEL_HOOK_LOG.jsonl")
GUARDIAN_ALERTS = os.path.join(ASTRA_ROOT, "state", "GUARDIAN_ALERTS.jsonl")

CHECK_INTERVAL = 300  # 5 minutes

def read_json(path):
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        return json.load(f)

def read_jsonl_tail(path, n=1):
    if not os.path.exists(path):
        return []
    with open(path, "r") as f:
        lines = [json.loads(l) for l in f if l.strip()]
        return lines[-n:] if lines else []

def summarize_health():
    trend = read_json(TREND_PATH) or {}
    defenses = read_jsonl_tail(DEFENSE_LOG)
    hooks = read_jsonl_tail(HOOK_LOG)

    integrity = trend.get("average_integrity", 0)
    risk = trend.get("risk_level", "unknown")
    violations = 0
    if defenses:
        violations = len(defenses[-1].get("violations", []))
    hook_status = "ok"
    if hooks:
        hook_status = hooks[-1].get("status", "ok")

    status = "healthy"
    if integrity < 90 or risk == "high" or hook_status != "ok":
        status = "critical"
    elif integrity < 95 or risk == "medium" or violations > 0:
        status = "warning"

    return {
        "timestamp": datetime.now().isoformat(),
        "integrity": integrity,
        "risk": risk,
        "violations": violations,
        "hook_status": hook_status,
        "status": status,
    }

def log_guardian_alert(alert):
    os.makedirs(os.path.dirname(GUARDIAN_ALERTS), exist_ok=True)
    with open(GUARDIAN_ALERTS, "a") as f:
        f.write(json.dumps(alert) + "\n")

def main():
    print("\n🧩 ASTRA GUARDIAN LINK v2 — Sentinel Integration\n")
    last_status = None
    while True:
        health = summarize_health()
        log_guardian_alert(health)

        ts = datetime.now().strftime("%H:%M:%S")
        status = health["status"].upper()
        print(f"[{ts}] Integrity {health['integrity']}% | Violations {health['violations']} | "
              f"Hook {health['hook_status']} | Status {status}")

        if health["status"] != last_status:
            if health["status"] == "warning":
                print("⚠️  Guardian Warning: Structural irregularities detected.")
            elif health["status"] == "critical":
                print("🚨 Guardian Critical: Sentinel reports unsafe conditions.")
            elif health["status"] == "healthy":
                print("✅ Guardian confirms stable integrity.")
            last_status = health["status"]

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
