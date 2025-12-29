import numpy as np
import os
import json
import traceback
from datetime import datetime, timezone
from pathlib import Path

from learning.learning_store import LearningStore
from learning.performance_tracker import PerformanceTracker
from learning.replay_buffer import ReplayBuffer

"""
Astra Intelligence - Learning Engine
------------------------------------
High-level intelligence system that updates Astra's learning weights
based on recent performance metrics and experience data.
"""


class LearningEngine:
    """Main adaptive intelligence engine that updates feature correlations and weights."""

    def __init__(self):
        self.store = LearningStore()
        self.tracker = PerformanceTracker()
        self.buffer = ReplayBuffer()
        self.state = self._load_state()
        self.cycle = 0
        self.avg_reward = 0.0
        self.correlation_weight = 0.0

    # === Metrics Writer ===
    def _update_learning_metrics(self):
        """Write current learning metrics to JSON safely."""
        metrics_path = Path("state/learning_metrics.json")
        metrics_data = {
            "cycle": int(getattr(self, "cycle", 0)),
            "avg_reward": float(getattr(self, "avg_reward", 0.0)),
            "correlation_weight": float(getattr(self, "correlation_weight", 0.0)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(metrics_path, "w") as f:
                json.dump(metrics_data, f, indent=2)
            print(f"[Astra LearningEngine] ✅ Metrics updated: {metrics_data}")
        except Exception as e:
            print(f"[Astra LearningEngine] ⚠️ Failed to update metrics: {e}")

    # === State Management ===
    def _load_state(self):
        """Load last saved weight state from LearningStore."""
        try:
            state = self.store.load_state()
            if state:
                print("[Astra LearningEngine] Loaded previous learning weights.")
                return state
        except Exception as e:
            print(f"[Astra LearningEngine] Warning: could not load previous state: {e}")
        return {"weights": np.ones(10), "timestamp": datetime.now(timezone.utc).isoformat()}

    def _save_state(self):
        """Persist the current learning weights."""
        try:
            self.store.save_state(self.state)
            print("[Astra LearningEngine] Learning weights saved.")
        except Exception as e:
            print(f"[Astra LearningEngine] Failed to save learning weights: {e}")

    # === Core Learning Computations ===
    def _compute_correlation_weights(self):
        """Compute new correlation weights based on replay buffer content."""
        samples = self.buffer.sample(100)
        if not samples:
            print("[Astra LearningEngine] No data available to compute correlations.")
            return self.state.get("weights", np.ones(10))

        try:
            flat_states = []
            for s in samples:
                st = s.get("state")

                if isinstance(st, dict):
                    st = list(st.values())

                if isinstance(st, (list, tuple)):
                    cleaned = []
                    for elem in st:
                        if isinstance(elem, dict):
                            cleaned.extend(list(elem.values()))
                        elif isinstance(elem, (int, float)):
                            cleaned.append(elem)
                        elif isinstance(elem, (list, tuple)):
                            cleaned.extend(
                                float(x) if isinstance(x, (int, float)) else 0.0
                                for x in elem
                            )
                        else:
                            cleaned.append(0.0)
                    st = cleaned

                if not isinstance(st, (list, tuple, np.ndarray)):
                    st = [float(st) if isinstance(st, (int, float)) else 0.0]

                flat_states.append(np.array(st, dtype=float))

            X = np.vstack(flat_states)
            y = np.array([s.get("reward", 0.0) for s in samples], dtype=float)

            corr = np.corrcoef(X.T, y)[-1, :-1]
            corr = np.nan_to_num(corr)
            corr = corr / (np.linalg.norm(corr) + 1e-9)

            print("[Astra LearningEngine] ✅ Correlation weights computed successfully.")
            self.correlation_weight = float(np.mean(corr))
            self.avg_reward = float(np.mean(y))
            return corr

        except Exception as e:
            print(f"[Astra LearningEngine] ❌ Correlation computation failed: {e}")
            traceback.print_exc()
            return self.state.get("weights", np.ones(10))

    def _adjust_weights_by_performance(self, corr_weights):
        """Adjust overall learning weights based on correlation and performance."""
        corr_weights = np.array(corr_weights, dtype=float)
        stats = self.tracker.get_recent_stats()
        acc = stats.get("accuracy", 0.5)
        win_rate = stats.get("win_rate", 0.5)

        performance_factor = (acc + win_rate) / 2.0
        prev_weights = np.array(
            self.state.get("weights", np.ones_like(corr_weights)), dtype=float
        )
        if prev_weights.shape != corr_weights.shape:
            prev_weights = np.ones_like(corr_weights)

        new_weights = prev_weights * 0.8 + corr_weights * 0.2 * (1 + performance_factor)
        new_weights = np.clip(
            new_weights / (np.linalg.norm(new_weights) + 1e-9), -1.0, 1.0
        )
        return new_weights

    def train(self):
        """Run the learning engine to update Astra’s meta-weights based on new data."""
        try:
            corr_weights = self._compute_correlation_weights()
            new_weights = self._adjust_weights_by_performance(corr_weights)
            self.state["weights"] = new_weights
            self.state["timestamp"] = datetime.now(timezone.utc).isoformat()
            self._save_state()
            self._update_learning_metrics()
            print("[Astra LearningEngine] ✅ Learning weights updated successfully.")
        except Exception as e:
            print(f"[Astra LearningEngine] ❌ LearningEngine training failed: {e}")
            traceback.print_exc()


# === External Entry Points ===
def train_learning_engine():
    engine = LearningEngine()
    engine.train()


def learning_signal():
    """Return a small multiplier reflecting recent learning trend."""
    try:
        tracker = PerformanceTracker()
        stats = tracker.get_recent_stats()
        accuracy = stats.get("accuracy", 0.5)
        win_rate = stats.get("win_rate", 0.5)
        factor = 1.0 + ((accuracy + win_rate) / 2.0 - 0.5) * 0.1
        return float(np.clip(factor, 0.9, 1.1))
    except Exception as e:
        print(f"[Astra Learning] Warning: learning_signal() failed: {e}")
        return 1.0


# === CLI Test Entry Point ===
if __name__ == "__main__":
    import sys

    if "--test" in sys.argv:
        print("[Astra LearningEngine] 🚀 Test mode activated.")
        try:
            engine = LearningEngine()
            engine.train()
        except Exception as e:
            print(f"[Astra LearningEngine] ⚠️ Test failed: {e}")
    else:
        print("[Astra LearningEngine] ℹ️ No test flag provided. Use '--test' to run diagnostics.")
