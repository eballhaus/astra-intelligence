import os, json, datetime, threading
from astra_dashboard.core.audit.auditlock_v1 import verify
from astra_dashboard.core.audit.recovery_daemon_v1 import monitor

LOG_DIR = "state/sentinel_logs"
os.makedirs(LOG_DIR, exist_ok=True)

def log_event(event_type, details):
    ts = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    record = {"timestamp": ts, "event": event_type, "details": details}
    path = os.path.join(LOG_DIR, f"log_{ts.replace(':','-')}.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2)
    print(f"[Sentinel] Logged: {event_type}")

def run_cycle():
    try:
        print("[Sentinel] Running integrity cycle...")
        verify()
        log_event("verify", "AuditLock verification completed.")
    except Exception as e:
        log_event("error", f"AuditLock verify failed: {e}")
    threading.Thread(target=lambda: monitor(interval=120), daemon=True).start()
    print("[Sentinel] RecoveryDaemon active (2-minute interval).")

def continuous_watch(interval=900):
    while True:
        run_cycle()
        time.sleep(interval)
