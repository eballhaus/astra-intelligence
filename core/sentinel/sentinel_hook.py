import os, json, subprocess
from datetime import datetime

ASTRA_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
HOOK_LOG = os.path.join(ASTRA_ROOT, "state", "SENTINEL_HOOK_LOG.jsonl")

def run_sentinel_defense():
    """Run Sentinel v4 after a file change to verify structural safety."""
    try:
        result = subprocess.run(
            ["python", "-m", "core.sentinel.sentinel_v4"],
            capture_output=True, text=True
        )
        output = result.stdout.strip()
        ok = "No structural policy violations" in output
        entry = {
            "timestamp": datetime.now().isoformat(),
            "result": output,
            "status": "ok" if ok else "warning"
        }
        with open(HOOK_LOG, "a") as f:
            f.write(json.dumps(entry) + "\n")
        return ok
    except Exception as e:
        print(f"⚠️ Sentinel hook error: {e}")
        return False

def on_file_created(filepath):
    """Called by Astra Engineer vMAX after any file creation."""
    print(f"🛰️ Sentinel Hook: checking {filepath}")
    safe = run_sentinel_defense()
    if not safe:
        print("🚨 Sentinel detected potential structural issues!")
    else:
        print("✅ Sentinel confirmed structural safety.")
