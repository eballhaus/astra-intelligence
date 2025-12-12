"""
Astra Intelligence - Continual Trainer
--------------------------------------
Continuously trains Astra's internal neural intelligence model using replayed experiences.

Responsibilities:
• Fetches training samples from ReplayBuffer
• Runs online training steps on the neural model
• Saves updated weights to LearningStore
• Tracks loss and performance metrics
• Operates safely under scheduler control

This trainer is designed to run continuously and incrementally.
"""

import traceback

import numpy as np

from astra_core.learning.learning_store import LearningStore
from astra_core.learning.performance_tracker import PerformanceTracker
from astra_core.learning.replay_buffer import ReplayBuffer


class ContinualTrainer:
    """
    Main online trainer for Astra's learning system.
    Performs incremental updates to the neural or statistical model using
    small batches from ReplayBuffer.
    """

    def __init__(self, batch_size: int = 32, learning_rate: float = 0.001):
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.store = LearningStore()
        self.performance = PerformanceTracker()

        # Initialize model weights (can be neural or regression-based)
        self.model = self._load_model()

    # === Model Management ===
    def _load_model(self):
        """Load model state from LearningStore."""
        try:
            state = self.store.load_state()
            if state and "weights" in state:
                print("[Astra Trainer] Loaded existing model weights.")
                return state
        except Exception as e:
            print(f"[Astra Trainer] Warning: could not load model: {e}")
        # fallback initial state
        return {"weights": np.random.rand(10), "bias": 0.0}

    def _save_model(self):
        """Persist model state to LearningStore."""
        try:
            self.store.save_state(self.model)
            print("[Astra Trainer] Model weights saved.")
        except Exception as e:
            print(f"[Astra Trainer] Failed to save model: {e}")

    # === Training Pipeline ===
    def _prepare_batch(self, buffer: ReplayBuffer):
        """Sample a mini-batch of training experiences."""
        samples = buffer.sample(self.batch_size)
        if not samples:
            return None, None, None
        X = np.array([s["state"] for s in samples])
        y_true = np.array([s["reward"] for s in samples])
        preds = np.array([s["prediction"] for s in samples])
        return X, y_true, preds

    def _train_step(self, X, y_true, preds):
        """
        Perform one gradient update step.
        Placeholder implementation: adjust weights based on prediction error.
        """
        try:
            errors = y_true - preds
            mean_error = np.mean(errors)
            grad = -2 * np.mean(X, axis=0) * mean_error
            self.model["weights"] -= self.learning_rate * grad
            self.model["bias"] -= self.learning_rate * mean_error
            loss = float(np.mean(errors**2))
            return loss
        except Exception as e:
            print(f"[Astra Trainer] Train step failed: {e}")
            return None

    def train(self, buffer: ReplayBuffer):
        """
        Run a full continual learning session.
        Pulls batches from ReplayBuffer and updates the model incrementally.
        """
        try:
            total_loss = []
            for i in range(5):  # 5 incremental mini-batch updates
                X, y_true, preds = self._prepare_batch(buffer)
                if X is None:
                    print("[Astra Trainer] No replay samples available.")
                    return False

                loss = self._train_step(X, y_true, preds)
                if loss is not None:
                    total_loss.append(loss)
                    print(f"[Astra Trainer] Batch {i+1}/5 | Loss: {loss:.6f}")

            # Save updated weights
            self._save_model()

            avg_loss = np.mean(total_loss) if total_loss else 0.0
            self.performance.record_training_result(loss=avg_loss)
            print(
                f"[Astra Trainer] ✅ Training complete | Avg Loss: {avg_loss:.6f}")

            return True

        except Exception as e:
            print(f"[Astra Trainer] ❌ Training failed: {e}")
            traceback.print_exc()
            return False
