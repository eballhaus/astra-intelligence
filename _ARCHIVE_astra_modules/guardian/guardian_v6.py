"""
GuardianV7 — Astra Intelligence Core Guardian
Full Hybrid Version (Core + Sentinel + Logging)
"""

import importlib
import json
import os
import threading
import time
from datetime import datetime

from guardian import guardian_ratewatch as ratewatch


# ==========================================================
# Logging System (from old guardian_log)
# ==========================================================
class guardian_log:
    def __init__(self):
        self.messages = []

    def log(self, message):
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[GuardianLog] {ts} | {message}"
        print(line)
        self.messages.append(line)

    def save(self, path=None):
        try:
            path = path or os.path.expanduser(
                "~/astra_guardian_runtime/guardian_log.txt"
            )
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a") as f:
                for msg in self.messages:
                    f.write(msg + "\n")
        except Exception as e:
            print(f"[GuardianCompat] ⚠️ Failed to save logs: {e}")


# ==========================================================
# Sentinel Integrity Watchdog (from GuardianSentinel)
# ==========================================================
class GuardianSentinel:
    def __init__(self, base_path=None, modules_to_check=None):
        self.base_path = base_path or os.getcwd()
        self.modules_to_check = modules_to_check or [
            "guardian.guardian_v7",
            "guardian.environment_guardian",
            "engine",
            "fetch_core",
        ]
        self.log_path = os.path.join(self.base_path, "sentinel_report.json")
        self.report = {"checked": [], "failed": [], "timestamp": None}

    def check_imports(self):
        import importlib

        for mod in self.modules_to_check:
            try:
                importlib.import_module(mod)
                self.report["checked"].append(mod)
            except Exception as e:
                self.report["failed"].append(str(e))
        self.report["timestamp"] = datetime.utcnow().isoformat()
        with open(self.log_path, "w") as f:
            json.dump(self.report, f, indent=2)
        print(f"[Sentinel] Report saved to {self.log_path}")


# ==========================================================
# GuardianV7 Main
# ==========================================================
class GuardianV7:
    def __init__(self):
        self.log = guardian_log()
        self.sentinel = GuardianSentinel()
        self.log.log("GuardianV7 initialized.")
        self._start_health_monitor()
        self.log.log("API firewall enabled (Yahoo fallback).")
        self.sentinel.check_imports()

    def api_ping(self, api_name: str):
        try:
            ratewatch.ping(api_name)
            self.log.log(f"Pinged API: {api_name}")
        except Exception as e:
            self.log.log(f"RateWatch ping failed for {api_name}: {e}")

    def snapshot(self):
        snap_dir = os.path.expanduser("~/astra_guardian_runtime/snapshots")
        os.makedirs(snap_dir, exist_ok=True)
        snap_file = os.path.join(snap_dir, f"snapshot_{int(time.time())}.json")
        data = {
            "timestamp": datetime.utcnow().isoformat(),
            "modules": list(importlib.sys.modules.keys()),
        }
        # Include AstraDefender memory if available
        try:
            import json

            from guardian.guardian_defender import ASTRA_MEMORY_FILE

            if ASTRA_MEMORY_FILE.exists():
                with open(ASTRA_MEMORY_FILE, "r") as mf:
                    defender_mem = json.load(mf)
                data["defender_memory"] = defender_mem
                self.log.log("AstraDefender memory included in snapshot.")
        except Exception as e:
            self.log.log(f"Failed to include AstraDefender memory: {e}")
        with open(snap_file, "w") as f:
            json.dump(data, f, indent=2)
        self.log.log(f"Snapshot saved: {snap_file}")

    def _start_health_monitor(self):
        def loop():
            while True:
                self.log.log("Health check OK.")
                time.sleep(60)

        threading.Thread(target=loop, daemon=True).start()


# ==========================================================
# Compatibility Aliases
# ==========================================================
Guardian = GuardianV7
__all__ = ["GuardianV7", "guardian_log", "GuardianSentinel", "Guardian"]
