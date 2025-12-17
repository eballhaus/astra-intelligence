import numpy as np
"""
Astra Intelligence - Learning Engine
------------------------------------
High-level intelligence system that updates Astra's learning weights
based on recent performance metrics and experience data.

Responsibilities:
• Analyze recent performance (accuracy, reward trends)
• Update weight correlations between agents and outcomes
• Provide live learning signal to other modules (e.g., AstraPrime)
• Persist new learning state via LearningStore
"""

import traceback
from datetime import datetime

import numpy as np

from learning.learning_store import LearningStore
from learning.performance_tracker import PerformanceTracker
from learning.replay_buffer import ReplayBuffer


class LearningEngine:
    """Main adaptive intelligence engine that updates feature correlations and weights."""

    def __init__(self):
        self.store = LearningStore()
        self.tracker = PerformanceTracker()
        self.buffer = ReplayBuffer()
        self.state = self._load_state()

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
        return {"weights": np.ones(10), "timestamp": datetime.utcnow().isoformat()}

    def _save_state(self):
        """Persist the current learning weights."""
        try:
            self.store.save_state(self.state)
            print("[Astra LearningEngine] Learning weights saved.")
        except Exception as e:
            print(f"[Astra LearningEngine] Failed to save learning weights: {e}")

    # === Core Learning Computations ===
    def _compute_correlation_weights(self):
        """
        Compute new correlation weights based on replay buffer content.
        This uses a simple covariance heuristic as a baseline.
        """
        samples = self.buffer.sample(100)
        if not samples:
            print("[Astra LearningEngine] No data available to compute correlations.")
            return self.state.get("weights", np.ones(10))

        try:
            X = np.array([s["state"] for s in samples])
            y = np.array([s["reward"] for s in samples])
            np.array([s["prediction"] for s in samples])

            # Correlation between state features and observed reward
            corr = np.corrcoef(X.T, y)[-1, :-1]
            corr = np.nan_to_num(corr)

            # Normalize correlation vector
            corr = corr / (np.linalg.norm(corr) + 1e-9)
            print("[Astra LearningEngine] Computed correlation weights.")
            return corr

        except Exception as e:
            print(f"[Astra LearningEngine] Correlation computation failed: {e}")
            traceback.print_exc()
            return self.state.get("weights", np.ones(10))

    def _adjust_weights_by_performance(self, corr_weights):
        corr_weights = np.array(corr_weights, dtype=float)
        """
        Adjust overall learning weights based on correlation and performance.
        """
        stats = self.tracker.get_recent_stats()
        acc = stats.get("accuracy", 0.5)
        win_rate = stats.get("win_rate", 0.5)

        # Scale weights toward better-performing features
        performance_factor = (acc + win_rate) / 2.0
        new_weights = np.array(self.state["weights"], dtype=float) * 0.8 + np.array(corr_weights, dtype=float) * 0.2 * (
            1 + performance_factor
        )

        # Normalize and clip
        new_weights = np.clip(
            new_weights / (np.linalg.norm(new_weights) + 1e-9), -1.0, 1.0
        )
        return new_weights

    def train(self):
        """
        Run the learning engine to update Astra’s meta-weights based on new data.
        """
        try:
            corr_weights = self._compute_correlation_weights()
            new_weights = self._adjust_weights_by_performance(np.array(corr_weights, dtype=float))

            self.state["weights"] = new_weights
            self.state["timestamp"] = datetime.utcnow().isoformat()

            self._save_state()
            print("[Astra LearningEngine] ✅ Learning weights updated successfully.")

        except Exception as e:
            print(f"[Astra LearningEngine] ❌ LearningEngine training failed: {e}")
            traceback.print_exc()


# === External Entry Points ===
def train_learning_engine():
    """Public helper to train the learning engine once."""
    engine = LearningEngine()
    engine.train()


def learning_signal():
    """
    Compute a short-term learning adjustment factor.
    Used by AstraPrime and other modules to scale decisions dynamically.
    Returns a float multiplier (e.g., 1.02 for positive learning trend).
    """
    try:
        tracker = PerformanceTracker()
        stats = tracker.get_recent_stats()

        accuracy = stats.get("accuracy", 0.5)
        win_rate = stats.get("win_rate", 0.5)

        # Compute a small multiplier based on recent performance (±5%)
        factor = 1.0 + ((accuracy + win_rate) / 2.0 - 0.5) * 0.1
        return float(np.clip(factor, 0.9, 1.1))

    except Exception as e:
        print(f"[Astra Learning] Warning: learning_signal() failed: {e}")
        return 1.0

# Compatibility alias for background learning manager
start_learning_cycle = train_learning_engine
