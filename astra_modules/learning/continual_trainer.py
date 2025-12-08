"""
Astra Intelligence - Continual Trainer
--------------------------------------
Continuously trains Astra's internal neural intelligence model using replayed experiences.

Responsibilities:
- Fetches training samples from ReplayBuffer
- Runs online training steps on the neural model
- Saves updated weights to LearningStore
- Tracks loss and performance metrics
- Operates safely under scheduler control
- Records ensemble forecasts for continual learning (Phase 2.3)

This trainer is designed to run continuously and incrementally.

Module Version: v2.3.1
"""

import traceback
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np
import numpy.typing as npt

from astra_modules.learning.learning_store import LearningStore
from astra_modules.learning.performance_tracker import PerformanceTracker
from astra_modules.learning.replay_buffer import ReplayBuffer


class ContinualTrainer:
    """
    Main online trainer for Astra's learning system.
    Performs incremental updates to the neural or statistical model using
    small batches from ReplayBuffer.

    Phase 2.3 additions:
    - Forecast feedback integration
    - Dynamic feature dimension detection
    - Reward update mechanism
    """

    AGENT_ORDER = ["momentum", "technical",
                   "volume", "risk", "psychology", "neural"]

    def __init__(
        self,
        batch_size: int = 32,
        learning_rate: float = 0.001,
        train_steps: int = 5,
        feature_dim: Optional[int] = None,
        log_callback: Optional[Callable[[str, str], None]] = None,
    ):
        """
        Initialize continual trainer.
        """
        self.batch_size = batch_size
        self.learning_rate = learning_rate
        self.train_steps = train_steps
        self.feature_dim = feature_dim

        # Core components
        self.store = LearningStore()
        self.performance = PerformanceTracker()
        self.replay_buffer = ReplayBuffer()

        # Logging
        self.log = log_callback or self._default_log

        # Initialize model weights (can be neural or regression-based)
        self.model = self._load_model()

    # === Logging ===
    def _default_log(self, message: str, level: str = "INFO") -> None:
        prefix = f"[{level}]" if level != "INFO" else ""
        print(f"{prefix}[Astra Trainer] {message}")

    # === Model Management ===
    def _load_model(self) -> Optional[Dict[str, Any]]:
        """Load model state from LearningStore."""
        try:
            state = self.store.load_state()
            if state and "weights" in state:
                if self.feature_dim is None:
                    self.feature_dim = len(state["weights"])
                if len(state["weights"]) == self.feature_dim:
                    self.log(f"Loaded model with {self.feature_dim} features.")
                    return state
                else:
                    self.log(
                        f"Model shape mismatch. Expected {self.feature_dim}, got {len(state['weights'])}. Reinitializing.",
                        "WARNING",
                    )
        except Exception as e:
            self.log(f"Could not load model: {e}", "ERROR")
        return None

    def _initialize_model(self, feature_dim: int) -> Dict[str, Any]:
        """Initialize model with specified feature dimension."""
        self.feature_dim = feature_dim
        model = {"weights": np.random.randn(feature_dim) * 0.01, "bias": 0.0}
        self.log(f"Initialized new model with {feature_dim} features.")
        return model

    def _save_model(self) -> None:
        """Persist model state to LearningStore."""
        if self.model is None:
            self.log("No model to save.", "WARNING")
            return
        try:
            self.store.save_state(self.model)
            self.log("Model weights saved.")
        except Exception as e:
            self.log(f"Failed to save model: {e}", "ERROR")
            traceback.print_exc()

    # === Training Pipeline ===
    def _prepare_batch(
        self, buffer: ReplayBuffer
    ) -> Tuple[Optional[npt.NDArray], Optional[npt.NDArray], Optional[npt.NDArray]]:
        """Sample a mini-batch of training experiences."""
        samples = buffer.sample(self.batch_size)
        if not samples:
            return None, None, None
        try:
            X = np.array([s["state"] for s in samples])
            y_true = np.array([s["reward"] for s in samples])
            preds = np.array([s["prediction"] for s in samples])
            return X, y_true, preds
        except (KeyError, ValueError) as e:
            self.log(f"Batch preparation failed: {e}", "ERROR")
            return None, None, None

    def _train_step(
        self, X: npt.NDArray, y_true: npt.NDArray, preds: npt.NDArray
    ) -> Optional[float]:
        """Perform one gradient update step."""
        try:
            if self.model is None:
                self.model = self._initialize_model(X.shape[1])
            if X.shape[1] != len(self.model["weights"]):
                self.log(
                    f"Feature mismatch: model has {len(self.model['weights'])}, got {X.shape[1]}",
                    "ERROR",
                )
                return None

            errors = y_true - preds
            mean_error = np.mean(errors)
            grad = -2 * np.mean(X, axis=0) * mean_error
            self.model["weights"] -= self.learning_rate * grad
            self.model["bias"] -= self.learning_rate * mean_error
            loss = float(np.mean(errors**2))
            return loss
        except Exception as e:
            self.log(f"Train step failed: {e}", "ERROR")
            traceback.print_exc()
            return None

    def train(self, buffer: Optional[ReplayBuffer] = None) -> bool:
        """Run a full continual learning session."""
        buffer = buffer or self.replay_buffer
        if buffer is None:
            self.log("No ReplayBuffer available for training.", "ERROR")
            return False
        try:
            total_loss = []
            for i in range(self.train_steps):
                X, y_true, preds = self._prepare_batch(buffer)
                if X is None:
                    self.log(
                        f"No samples at batch {i+1}/{self.train_steps}. Stopping early.",
                        "WARNING",
                    )
                    break
                loss = self._train_step(X, y_true, preds)
                if loss is not None:
                    total_loss.append(loss)
                    self.log(
                        f"Batch {i+1}/{self.train_steps} | Loss: {loss:.6f}")
            if total_loss:
                self._save_model()
                avg_loss = np.mean(total_loss)
                self.performance.record_training_result(loss=avg_loss)
                self.log(
                    f"✅ Training complete | Batches: {len(total_loss)} | Avg Loss: {avg_loss:.6f}"
                )
                return True
            else:
                self.log(
                    "No training performed (no samples available).", "WARNING")
                return False
        except Exception as e:
            self.log(f"Training failed: {e}", "ERROR")
            traceback.print_exc()
            return False

    # === Forecast Feedback Integration (Phase 2.3) ===
    def _trend_to_scalar(self, trend: str) -> float:
        return {"bullish": 1.0, "bearish": -1.0, "neutral": 0.0}.get(trend.lower(), 0.0)

    def _validate_forecast(self, forecast: Dict[str, Any]) -> bool:
        """Validate forecast structure and key ranges."""
        required = {"symbol", "confidence", "trend", "ensemble_score"}
        if not required.issubset(forecast.keys()):
            missing = required - forecast.keys()
            self.log(f"Invalid forecast: missing {missing}", "WARNING")
            return False
        try:
            confidence = float(forecast["confidence"])
            if not 0.0 <= confidence <= 1.0:
                self.log(f"Invalid confidence {confidence}", "WARNING")
                return False
            _ = self._trend_to_scalar(forecast["trend"])
            return True
        except (ValueError, TypeError) as e:
            self.log(f"Forecast validation error: {e}", "ERROR")
            return False

    def record_forecast(self, forecast: Dict[str, Any]) -> bool:
        """Accepts forecasts from ForecastEngine and stores as replay experiences."""
        try:
            if not self._validate_forecast(forecast):
                return False

            # Build feature vector
            state = [
                forecast.get("ensemble_score", 0.0),
                forecast.get("confidence", 0.0),
                self._trend_to_scalar(forecast.get("trend", "neutral")),
                forecast.get("predicted_change", 0.0),
            ]

            agent_scores = forecast.get("agent_scores", {})
            state.extend([agent_scores.get(k, 0.0) for k in self.AGENT_ORDER])

            # Optional normalization (keep bounded)
            state = np.clip(state, -2.0, 2.0).tolist()

            experience = {
                "state": state,
                "reward": 0.0,
                "prediction": forecast.get("ensemble_score", 0.0),
                "symbol": forecast.get("symbol", "UNKNOWN"),
                "timestamp": forecast.get("timestamp"),
            }

            if hasattr(self.replay_buffer, "store"):
                self.replay_buffer.store(experience)
                self.log(f"✅ Recorded forecast for {experience['symbol']}")
            else:
                self.log("ReplayBuffer missing store() method.", "ERROR")
                return False

            if hasattr(self.performance, "log_prediction"):
                try:
                    self.performance.log_prediction(forecast)
                except Exception as e:
                    self.log(
                        f"PerformanceTracker logging failed: {e}", "WARNING")

            return True
        except Exception as e:
            self.log(f"Forecast recording failed: {e}", "ERROR")
            traceback.print_exc()
            return False

    # === Phase 2.4: Outcome Updates ===
    def update_forecast_outcome(
        self, symbol: str, timestamp: str, actual_return: float
    ) -> bool:
        """
        Updates stored forecasts with realized market returns.
        Called when true price data becomes available.
        """
        try:
            if self.replay_buffer is None or not hasattr(
                self.replay_buffer, "update_reward"
            ):
                self.log(
                    "ReplayBuffer does not support reward updates.", "WARNING")
                return False

            # Compute reward: positive if direction correct, scaled by return
            for exp in getattr(self.replay_buffer, "buffer", []):
                if exp["symbol"] == symbol and exp["timestamp"] == timestamp:
                    predicted_sign = np.sign(exp["prediction"])
                    actual_sign = np.sign(actual_return)
                    reward = 1.0 if predicted_sign == actual_sign else -1.0
                    exp["reward"] = reward * abs(actual_return)
                    self.log(
                        f"Updated reward for {symbol} ({timestamp}) → {exp['reward']:.4f}"
                    )
                    return True

            self.log(
                f"No matching forecast found for {symbol} at {timestamp}", "WARNING"
            )
            return False
        except Exception as e:
            self.log(f"Reward update failed: {e}", "ERROR")
            traceback.print_exc()
            return False

    def __repr__(self) -> str:
        return f"<ContinualTrainer features={self.feature_dim}, buffer={len(getattr(self.replay_buffer, 'buffer', []))}>"
