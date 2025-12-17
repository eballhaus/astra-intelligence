"""
Astra Intelligence - Learning Store
-----------------------------------
Persistent storage for Astra's learning models, weights, and metadata.

Responsibilities:
• Save and load model/weight state to disk
• Provide lightweight persistence for learning and training modules
• Validate stored data integrity
• Safely recover from missing or corrupted states
"""

import json
import os
import traceback
from datetime import datetime
from pathlib import Path


class LearningStore:
    """Persistent store for Astra’s learned weights and model state."""

    def __init__(self):
        self.store_path = Path("astra_modules/state/astra_learning_store.json")
        self._ensure_directory()

    # === Internal Helpers ===
    def _ensure_directory(self):
        """Ensure the storage directory exists."""
        try:
            os.makedirs(self.store_path.parent, exist_ok=True)
        except Exception as e:
            print(f"[Astra LearningStore] Directory creation failed: {e}")

    def _default_state(self):
        """Return an empty default model state."""
        return {
            "weights": [],
            "bias": 0.0,
            "timestamp": datetime.datetime.utcnow().isoformat(),
            "meta": {
                "version": "1.0",
                "engine": "astra_learning",
                "notes": "Default initialized state",
            },
        }

    # === Core Persistence Methods ===
    def save_state(self, state: dict):
        """Save the learning state to disk."""
        try:
            state["timestamp"] = datetime.datetime.utcnow().isoformat()
            with open(self.store_path, "w") as f:
                json.dump(_sanitize_for_json(state), f, indent=2)
            print(f"[Astra LearningStore] State saved at {state['timestamp']}")
        except Exception as e:
            print(f"[Astra LearningStore] Failed to save state: {e}")
            traceback.print_exc()

    def load_state(self) -> dict:
        """Load the latest learning state."""
        try:
            if not self.store_path.exists():
                print("[Astra LearningStore] No saved state found, using default.")
                return self._default_state()
            with open(self.store_path, "r") as f:
                state = _safe_json_load(filepath)
            return state
        except Exception as e:
            print(f"[Astra LearningStore] Failed to load state: {e}")
            traceback.print_exc()
            return self._default_state()

    def reset(self):
        """Reset the learning store to default."""
        try:
            state = self._default_state()
            self.save_state(state)
            print("[Astra LearningStore] Reset to default state.")
        except Exception as e:
            print(f"[Astra LearningStore] Failed to reset store: {e}")

    # === Metadata ===
    def get_metadata(self):
        """Return basic information about the current learning state."""
        try:
            state = self.load_state()
            return {
                "timestamp": state.get("timestamp"),
                "version": state.get("meta", {}).get("version", "unknown"),
                "engine": state.get("meta", {}).get("engine", "unknown"),
                "weights_count": len(state.get("weights", [])),
            }
        except Exception as e:
            print(f"[Astra LearningStore] Metadata retrieval failed: {e}")
            return {}

# ---- JSON sanitizer for NumPy, datetime, etc. ----
import numpy as np, datetime

def _sanitize_for_json(obj):
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, (np.float32, np.float64, np.int32, np.int64)):
        return obj.item()
    if isinstance(obj, (datetime.date, datetime.datetime)):
        return obj.isoformat()
    if isinstance(obj, dict):
        return {k: _sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_for_json(i) for i in obj]
    return obj
# ---- end sanitizer ----

# ---- Safe JSON loader to prevent crashes on empty/corrupt files ----
def _safe_json_load(filepath):
    import os, json
    if not os.path.exists(filepath) or os.path.getsize(filepath) == 0:
        return {}
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return {}
# ---- End safe loader ----
