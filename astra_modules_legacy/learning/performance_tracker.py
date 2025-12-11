"""
Astra Intelligence - Performance Tracker
----------------------------------------
Logs Astra’s performance metrics and learning outcomes.

Responsibilities:
• Record forecast results and training metrics
• Track reward statistics, win rate, and accuracy
• Provide data for LearningEngine and dashboard display
• Persist stats safely to disk
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np


class PerformanceTracker:
    """Tracks performance and learning metrics for Astra Intelligence."""

    def __init__(self):
        self.metrics_path = Path("astra_modules/state/astra_performance.json")
        self.data = self._load()

    # === Persistence ===
    def _load(self):
        """Load historical performance data."""
        try:
            if self.metrics_path.exists():
                with open(self.metrics_path, "r") as f:
                    data = json.load(f)
                    return data
        except Exception as e:
            print(f"[Astra Tracker] Warning: failed to load metrics: {e}")
        return {"records": [], "training_log": []}

    def _save(self):
        """Persist performance data."""
        try:
            self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.metrics_path, "w") as f:
                json.dump(self.data, f, indent=2)
        except Exception as e:
            print(f"[Astra Tracker] Warning: failed to save metrics: {e}")

    # === Core Recording Methods ===
    def record_performance(self, symbol: str, reward: float):
        """Record a reward outcome for a forecast."""
        try:
            record = {
                "symbol": symbol,
                "reward": reward,
                "timestamp": datetime.utcnow().isoformat(),
            }
            self.data["records"].append(record)
            # Keep last 1000 records only
            self.data["records"] = self.data["records"][-1000:]
            self._save()
        except Exception as e:
            print(f"[Astra Tracker] Failed to record performance: {e}")

    def record_training_result(self, loss: float):
        """Log a training result entry."""
        try:
            entry = {"timestamp": datetime.utcnow().isoformat(),
                     "loss": float(loss)}
            self.data["training_log"].append(entry)
            self.data["training_log"] = self.data["training_log"][-200:]
            self._save()
        except Exception as e:
            print(f"[Astra Tracker] Failed to record training result: {e}")

    # === Statistics & Learning Data ===
    def get_recent_stats(self, n: int = 200):
        """Return recent accuracy, win rate, and average reward."""
        try:
            records = self.data.get("records", [])[-n:]
            if not records:
                return {"accuracy": 0.5, "win_rate": 0.5, "avg_reward": 0.0}

            rewards = np.array([r["reward"] for r in records])
            positive = np.sum(rewards > 0)
            win_rate = positive / len(rewards)
            avg_reward = np.mean(rewards)
            accuracy = win_rate  # accuracy == win rate for trading outcomes

            return {
                "accuracy": float(accuracy),
                "win_rate": float(win_rate),
                "avg_reward": float(avg_reward),
            }
        except Exception as e:
            print(f"[Astra Tracker] Failed to compute stats: {e}")
            return {"accuracy": 0.5, "win_rate": 0.5, "avg_reward": 0.0}

    def get_learning_curve(self, n: int = 50):
        """Return recent training losses as a learning curve."""
        try:
            log = self.data.get("training_log", [])[-n:]
            timestamps = [x["timestamp"] for x in log]
            losses = [x["loss"] for x in log]
            return {"timestamps": timestamps, "losses": losses}
        except Exception as e:
            print(f"[Astra Tracker] Failed to load learning curve: {e}")
            return {"timestamps": [], "losses": []}

    def get_accuracy_stats(self):
        """Alias for get_recent_stats."""
        return self.get_recent_stats()
