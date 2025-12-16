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

# ============================================================
# === ASTRA GUARDIAN — Rate & Quota Monitor (v1) =============
# ============================================================
import time

_api_counters = {}

def rate_safe(api_name, interval=60, daily_limit=None):
    """Prevent overuse of the same API globally."""
    now = time.time()
    rec = _api_counters.get(api_name, {"ts": 0, "count": 0})

    if now - rec["ts"] < interval:
        guardian_log.info(f"[RateSafe] {api_name} cooldown active ({interval}s).")
        return False

    if daily_limit and rec["count"] >= daily_limit:
        guardian_log.warn(f"[RateSafe] {api_name} daily limit reached ({daily_limit}).")
        return False

    _api_counters[api_name] = {"ts": now, "count": rec["count"] + 1}
    return True

def api_usage_report():
    """Print a summary of API usage counts."""
    guardian_log.info("[Guardian] API Usage Summary:")
    for api, rec in _api_counters.items():
        guardian_log.info(f"  {api}: {rec['count']} calls today.")


# --- Patch: Add warning() compatibility if missing ---
try:
    if not hasattr(guardian_log, "warning"):
        guardian_log.warning = guardian_log.info
        guardian_log.info("[Guardian] Added .warning() alias for compatibility.")
except Exception as e:
    print("[Guardian Patch] Failed to add warning alias:", e)
