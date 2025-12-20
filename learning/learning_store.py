import os
import json
import numpy as np
import datetime

# =========================================================
#  Astra LearningStore — Safe persistent state handler
# =========================================================


class LearningStore:
    def __init__(self, filepath="learning/learning_state.json"):
        self.filepath = filepath
        self.state = {
            "weights": [],
            "timestamp": datetime.datetime.utcnow().isoformat(),
        }
        self.load_state()

    # -----------------------------------------------------
    #  Helper — JSON sanitizer (NumPy, datetime, etc.)
    # -----------------------------------------------------
    def _sanitize_for_json(self, obj):
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, (np.float32, np.float64, np.int32, np.int64)):
            return obj.item()
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        if isinstance(obj, dict):
            return {k: self._sanitize_for_json(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self._sanitize_for_json(i) for i in obj]
        return obj

    # -----------------------------------------------------
    #  Safe load
    # -----------------------------------------------------
    def load_state(self):
        try:
            if not os.path.exists(self.filepath) or os.path.getsize(self.filepath) == 0:
                print("[Astra LearningStore] No previous state found.")
                return

            with open(self.filepath, "r") as f:
                state = json.load(f)
                if isinstance(state, dict):
                    self.state.update(state)
                    print("[Astra LearningStore] ✅ State loaded successfully.")
                else:
                    print(
                        "[Astra LearningStore] ⚠️ Invalid state format; using defaults."
                    )

        except json.JSONDecodeError:
            print("[Astra LearningStore] ⚠️ Corrupt JSON file. Reinitializing.")
        except Exception as e:
            print(f"[Astra LearningStore] Failed to load state: {e}")

    # -----------------------------------------------------
    #  Safe save
    # -----------------------------------------------------
    def save_state(self, new_state=None):
        try:
            if new_state:
                self.state.update(new_state)
            self.state["timestamp"] = datetime.datetime.utcnow().isoformat()

            with open(self.filepath, "w") as f:
                json.dump(self._sanitize_for_json(self.state), f, indent=2)
            print(f"[Astra LearningStore] ✅ State saved at {self.state['timestamp']}")
        except Exception as e:
            print(f"[Astra LearningStore] Failed to save state: {e}")


# =========================================================
#  Standalone test
# =========================================================
if __name__ == "__main__":
    store = LearningStore()
    store.save_state({"weights": np.array([0.3, 0.7, 0.9])})
