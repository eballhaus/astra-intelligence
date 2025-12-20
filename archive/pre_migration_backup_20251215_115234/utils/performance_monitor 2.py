import time
import json
import os
from datetime import datetime
from guardian.guardian_v6 import guardian_log

LOG_PATH = "logs/performance_profile.json"

def record(event: str, duration: float):
    os.makedirs("logs", exist_ok=True)
    try:
        data = {"timestamp": datetime.utcnow().isoformat(), "event": event, "duration": duration}
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(data) + "\n")
        guardian_log(f"[Perf] {event}: {duration:.3f}s")
    except Exception as e:
        guardian_log(f"[Perf] Warning while logging {event}: {e}")

def measure(event):
    def decorator(func):
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            duration = time.perf_counter() - start
            record(event, duration)
            return result
        return wrapper
    return decorator
