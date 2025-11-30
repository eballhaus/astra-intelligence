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
from pathlib import Path
from datetime import datetime
import traceback


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
            "timestamp": datetime.utcnow().isoformat(),
            "meta": {
                "version": "1.0",
                "engine": "astra_learning",
                "notes": "Default initialized state"
            }
        }

    # === Core Persistence Methods ===
    def save_state(self, state: dict):
        """Save the learning state to disk."""
        try:
            state["timestamp"] = datetime.utcnow().isoformat()
            with open(self.store_path, "w") as f:
                json.dump(state, f, indent=2)
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
                state = json.load(f)
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
                "weights_count": len(state.get("weights", []))
            }
        except Exception as e:
            print(f"[Astra LearningStore] Metadata retrieval failed: {e}")
            return {}
