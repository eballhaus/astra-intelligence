# -*- coding: utf-8 -*-
"""
Guardian V7 — Unified System Logger & Health Monitor
----------------------------------------------------
Provides a centralized logging and self-healing interface
for Astra Intelligence. Used by all major modules.
"""

import datetime
import threading

class GuardianV7:
    """Unified guardian system for safety, logging, and state health."""
    def __init__(self):
        self._lock = threading.Lock()
        self._events = []

    def log(self, level: str, message: str):
        """Record a log event."""
        with self._lock:
            entry = {
                "timestamp": datetime.datetime.utcnow().isoformat(timespec="seconds"),
                "level": level.upper(),
                "message": message,
            }
            self._events.append(entry)
            print(f"[GuardianV7] {entry['timestamp']} | {entry['level']} | {entry['message']}")

    def get_recent_events(self, limit: int = 10):
        """Return the most recent Guardian log events."""
        return self._events[-limit:]

    def info(self, message: str):
        self.log("INFO", message)

    def warning(self, message: str):
        self.log("WARN", message)

    def error(self, message: str):
        self.log("ERROR", message)


# Create a global Guardian instance and unified logger alias
guardian_log = GuardianV7()
