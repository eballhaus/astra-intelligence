"""
Astra Intelligence - Replay Buffer
----------------------------------
Experience replay memory for Astra’s continual learning system.

Responsibilities:
• Store (state, prediction, reward) tuples for learning
• Persist data safely on disk
• Provide random batches for online training
• Manage buffer size and cleanup
"""

import json
import os
import random
from datetime import datetime
from pathlib import Path

import numpy as np


class ReplayBuffer:
    """Persistent experience replay memory for Astra Intelligence."""

    def __init__(self, capacity: int = 5000):
        self.capacity = capacity
        self.buffer = []
        self.buffer_path = Path("astra_modules/state/astra_replay_buffer.json")
        self._load()

    # === Persistence Management ===
    def _load(self):
        """Load saved replay buffer from disk if available."""
        try:
            if self.buffer_path.exists():
                with open(self.buffer_path, "r") as f:
                    self.buffer = json.load(f)
                print(
                    f"[Astra ReplayBuffer] Loaded {len(self.buffer)} experiences.")
        except Exception as e:
            print(f"[Astra ReplayBuffer] Warning: failed to load buffer: {e}")
            self.buffer = []

    def _save(self):
        """Save buffer state to disk."""
        try:
            os.makedirs(self.buffer_path.parent, exist_ok=True)
            with open(self.buffer_path, "w") as f:
                json.dump(self.buffer[-self.capacity:], f, indent=2)
        except Exception as e:
            print(f"[Astra ReplayBuffer] Warning: failed to save buffer: {e}")

    # === Core Methods ===
    def add(self, state, prediction, reward, symbol=None, confidence=None):
        """Add a new experience tuple."""
        try:
            sample = {
                "state": (
                    np.array(state).tolist() if isinstance(
                        state, np.ndarray) else state
                ),
                "prediction": float(prediction),
                "reward": float(reward),
                "symbol": symbol or "N/A",
                "confidence": confidence,
                "timestamp": datetime.utcnow().isoformat(),
            }

            self.buffer.append(sample)
            if len(self.buffer) > self.capacity:
                self.buffer = self.buffer[-self.capacity:]

            self._save()
        except Exception as e:
            print(f"[Astra ReplayBuffer] Failed to add experience: {e}")

    def sample(self, batch_size: int = 32):
        """Return a random batch of experience samples."""
        if not self.buffer:
            return []
        try:
            return random.sample(self.buffer, min(len(self.buffer), batch_size))
        except ValueError:
            return self.buffer

    def clear(self):
        """Reset the replay buffer."""
        self.buffer = []
        self._save()
        print("[Astra ReplayBuffer] Cleared.")

    def __len__(self):
        """Number of stored experiences."""
        return len(self.buffer)

    # === Advanced ===
    def get_recent_rewards(self, n: int = 100):
        """Return the most recent N rewards for analysis."""
        if not self.buffer:
            return []
        rewards = [s.get("reward", 0.0) for s in self.buffer[-n:]]
        return rewards

    def get_recent_accuracy(self):
        """Compute approximate recent accuracy from reward sign."""
        rewards = self.get_recent_rewards(200)
        if not rewards:
            return 0.0
        positive = sum(1 for r in rewards if r > 0)
        return positive / len(rewards)
