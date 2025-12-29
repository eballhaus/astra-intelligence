import os, json, sys
from datetime import datetime

ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
POLICY_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_POLICY.json")
LOG_PATH = os.path.join(ASTRA_ROOT, "state", "SENTINEL_DEFENSE_LOG.jsonl")

DEFAULT_POLICY = {
    "ui/": ["*.py", "*.css", "*.json"],
    "core/": ["*.py"],
    "state/": ["*.json", "*.py"],
    "learning/": ["*.py"],
    "forecast/": ["*.py"],
    "guardian/": ["*.py"]
}

def load_policy():
    if not os.path.exists(POLICY_PATH):
        with open(POLICY_PATH, "w") as f:
            json.dump(DEFAULT_POLICY, f, indent=4)
        print("⚙️ Default Sentinel policy created.")
        return DEFAULT_POLICY
    with open(POLICY_PATH, "r") as f:
        return json.load(f)

def check_policy(policy):
    violations = []
    for folder, allowed_patterns in policy.items():
        path = os.path.join(ASTRA_ROOT, folder)
        if not os.path.exists(path): continue
        for root, _, files in os.walk(path):
            for f in files:
                ext = os.path.splitext(f)[1]
                if ext and not any(p.endswith(ext) for p in allowed_patterns):
                    violations.append(os.path.join(root, f))
    return violations

def log_violation(vlist):
    if not vlist: return
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a") as f:
        f.write(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "violations": vlist
        }) + "\n")

def main():
    print("\n🛡️ ASTRA SENTINEL v4 — Structural Defense\n")
    policy = load_policy()
    violations = check_policy(policy)
    if violations:
        log_violation(violations)
        print(f"🚨 {len(violations)} violations detected! Details logged in SENTINEL_DEFENSE_LOG.jsonl")
        sys.exit(1)
    else:
        print("✅ No structural policy violations detected.")
        sys.exit(0)

if __name__ == "__main__":
    main()


def run_report_only():
    """Read-only diagnostic mode for Sentinel v4 (Canonical-Lock Safe)."""
    print("[Sentinel] 🔎 Running in report-only mode...")
    try:
        import json, os
        with open(os.path.join(os.getcwd(), "sentinel_lock_manifest.json")) as f:
            manifest = json.load(f)
        print("[Sentinel] Manifest loaded: OK")
        print("[Sentinel] No destructive actions permitted under Canonical Lock.")
    except Exception as e:
        print(f"[Sentinel] ⚠️ Report-only mode failed: {e}")
