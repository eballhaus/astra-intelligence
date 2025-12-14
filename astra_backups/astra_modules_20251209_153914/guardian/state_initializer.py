"""
Astra Intelligence - State Initializer
--------------------------------------
Ensures Astra’s core state directories and data files exist before startup.
This guarantees all learning, performance, and replay components
have valid JSON containers to write to.

Runs automatically during system startup or dashboard load.
"""

import json
import os
from pathlib import Path


class StateInitializer:
    """Ensures Astra’s state files and folders exist safely."""

    def __init__(self):
        self.state_dir = Path("astra_modules/state")
        self.files = {
            "astra_learning_store.json": {
                "weights": [],
                "bias": 0.0,
                "timestamp": "",
                "meta": {"version": "1.0", "engine": "astra_learning"},
            },
            "astra_performance.json": {"records": [], "training_log": []},
            "astra_replay_buffer.json": [],
        }

    def run(self):
        """Create state directory and files if missing."""
        try:
            os.makedirs(self.state_dir, exist_ok=True)
            for name, default_content in self.files.items():
                file_path = self.state_dir / name
                if not file_path.exists():
                    with open(file_path, "w") as f:
                        json.dump(default_content, f, indent=2)
                    print(f"[Astra Guardian] Created missing file: {file_path}")
            print("[Astra Guardian] ✅ State directory verified and ready.")
        except Exception as e:
            print(f"[Astra Guardian] ⚠️ State initialization failed: {e}")


def ensure_state_ready():
    """Convenience method for import-based initialization."""
    StateInitializer().run()


if __name__ == "__main__":
    ensure_state_ready()
