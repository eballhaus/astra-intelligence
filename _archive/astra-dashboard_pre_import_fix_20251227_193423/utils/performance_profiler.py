import time
import json
import os
from contextlib import contextmanager
from datetime import datetime

LOG_PATH = "logs/performance_profile.json"


class Profiler:
    """Lightweight profiler for import and execution timing."""

    _records = {}

    @staticmethod
    @contextmanager
    def timer(name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = round(time.perf_counter() - start, 4)
            Profiler._records[name] = duration
            Profiler._save()

    @staticmethod
    def _save():
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        timestamp = datetime.utcnow().isoformat()
        data = {"timestamp": timestamp, "records": Profiler._records}
        with open(LOG_PATH, "w") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def log(name: str, duration: float):
        Profiler._records[name] = duration
        Profiler._save()
