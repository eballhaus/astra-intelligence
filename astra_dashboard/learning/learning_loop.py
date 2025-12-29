import time, os, json
from datetime import datetime, timezone
from astra_dashboard.learning.learning_manager import start_background_learning
from astra_dashboard.core.guardian.guardian_v7 import GuardianV7

INTERVAL_MINUTES = 2
MAX_LOG_LINES = 1000

LOG_PATH = os.path.join("state", "learning_log.txt")
METRICS_PATH = os.path.join("state", "learning_metrics.json")

guardian = GuardianV7()

def get_guardian_status():
    """Return simple Guardian health summary string."""
    try:
        if hasattr(guardian, "api_usage_report"):
            report = guardian.api_usage_report()
            latency = report.get("latency_ms", "N/A")
            status = "✅ API OK" if report else "⚠️ No Data"
            return f"Guardian: {status} ({latency} ms)"
        else:
            return "Guardian: ✅ Active"
    except Exception as e:
        return f"Guardian: ⚠️ {e}"

def append_summary_line():
    """Append a readable summary of the latest metrics and Guardian heartbeat."""
    try:
        with open(METRICS_PATH, "r") as f:
            data = json.load(f)
        last = data[-1] if isinstance(data, list) else data
        reward = last.get("avg_reward", "N/A")
        conf = last.get("correlation_weight", last.get("confidence", "N/A"))
        cycle = last.get("cycle", "?")
        guardian_status = get_guardian_status()
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        line = f"[{timestamp}] Reward: {reward} | Confidence: {conf} | Cycle: {cycle} | {guardian_status}\n"

        with open(LOG_PATH, "a") as log:
            log.write(line)

        with open(LOG_PATH, "r") as log:
            lines = log.readlines()
        if len(lines) > MAX_LOG_LINES:
            with open(LOG_PATH, "w") as log:
                log.writelines(lines[-MAX_LOG_LINES:])
            print(f"[Astra Loop] 🧹 Trimmed log to last {MAX_LOG_LINES} lines.")
    except Exception as e:
        print(f"[Astra Loop] ⚠️ Could not append summary: {e}")

try:
    print(f"[Astra Loop] 🚀 Starting continuous learning loop ({INTERVAL_MINUTES}-minute interval)...")
    while True:
        print(f"[Astra Loop] ⏱️ Cycle started at {datetime.now(timezone.utc).isoformat()}")
        start_background_learning(test_mode=True)
        append_summary_line()
        print(f"[Astra Loop] ✅ Cycle completed, sleeping for {INTERVAL_MINUTES} min\n")
        print(f"[Astra Loop] ✅ Metrics saved to state/learning_metrics.json", flush=True)
        time.sleep(INTERVAL_MINUTES * 60)
except KeyboardInterrupt:
    print("[Astra Loop] 🛑 Stopped manually.")
