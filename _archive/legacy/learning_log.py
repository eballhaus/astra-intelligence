"""
learning_log.py — Astra Learning Metric Logger
Tracks and persists learning metrics like accuracy, loss, drift, and reward.
"""

import os
import json
from datetime import datetime
from core.guardian.guardian_v7 import GuardianV7

guardian = GuardianV7()

LOG_PATH = "state/learning_metrics.json"


class LearningLog:
    def __init__(self):
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        if not os.path.exists(LOG_PATH):
            with open(LOG_PATH, "w") as f:
                json.dump([], f)
        self._buffer = []

    def log(self, phase: str, metrics: dict):
        """Record a set of metrics."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "phase": phase,
            "metrics": metrics,
        }
        self._buffer.append(entry)
        guardian.info(f"📈 Logged learning metrics ({phase}): {metrics}")
        self._flush()

    def _flush(self):
        """Persist buffered metrics to disk."""
        try:
            with open(LOG_PATH, "r") as f:
                data = json.load(f)
            data.extend(self._buffer)
            with open(LOG_PATH, "w") as f:
                json.dump(data, f, indent=2)
            self._buffer.clear()
        except Exception as e:
            guardian.error(f"Error writing learning log: {e}")

    def get_recent(self, limit: int = 10):
        """Retrieve recent metric entries."""
        try:
            with open(LOG_PATH, "r") as f:
                data = json.load(f)
            return data[-limit:]
        except Exception:
            return []
