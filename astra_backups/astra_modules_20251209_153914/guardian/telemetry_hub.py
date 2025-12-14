"""
telemetry_hub.py
──────────────────────────────────────────────────────────────
Guardian Telemetry Hub (Phase 2.9-A)
Collects and exports heartbeat and training telemetry to JSON.

Features:
- Writes rolling JSON logs to /logs/telemetry.jsonl
- Keeps latest snapshot in telemetry_latest.json
- Thread-safe and dependency-free
"""

import json
import os
import threading
from datetime import datetime
from typing import Any, Dict


class TelemetryHub:
    """Centralized lightweight telemetry exporter."""

    def __init__(self, base_dir: str = None):
        self.lock = threading.Lock()
        self.base_dir = base_dir or os.path.join(os.getcwd(), "logs")
        os.makedirs(self.base_dir, exist_ok=True)
        self.telemetry_path = os.path.join(self.base_dir, "telemetry.jsonl")
        self.snapshot_path = os.path.join(self.base_dir, "telemetry_latest.json")

    def record(self, data: Dict[str, Any]) -> None:
        """Safely write telemetry entry to rolling log and snapshot."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = {"timestamp": timestamp, **data}

        with self.lock:
            try:
                # Append JSONL record
                with open(self.telemetry_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry) + "\n")

                # Write latest snapshot
                with open(self.snapshot_path, "w", encoding="utf-8") as f:
                    json.dump(entry, f, indent=2)
            except Exception as e:
                print(f"[TelemetryHub] ⚠️ Failed to write telemetry: {e}")

    def load_latest(self) -> Dict[str, Any]:
        """Return last recorded telemetry snapshot."""
        try:
            with open(self.snapshot_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
