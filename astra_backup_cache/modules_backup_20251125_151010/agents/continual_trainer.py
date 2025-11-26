"""
ContinualTrainer – Astra Intelligence (Phase-100)
-------------------------------------------------
Provides experience replay and incremental training
for the NeuralAgent under GuardianV6 supervision.
"""

import os
import sys
import json
import torch
from pathlib import Path
from datetime import datetime

# --- Fix Python import path so "astra_modules" is accessible ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# --------------------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.neural_agent import NeuralAgent


class ReplayBuffer:
    """Stores recent training samples for continual learning."""
    def __init__(self, max_size=5000, base_path=None):
        self.max_size = max_size
        self.base_path = base_path or os.getcwd()
        self.buffer_file = Path(self.base_path) / "astra_learning.json"
        self.guardian = GuardianV6(self.base_path)
        self._load()

    def _load(self):
        if self.buffer_file.exists():
            try:
                with open(self.buffer_file, "r") as f:
                    self.buffer = json.load(f)
            except Exception:
                self.buffer = []
        else:
            self.buffer = []

    def add(self, x, y):
        """Add a new training sample (as lists)."""
        if len(self.buffer) >= self.max_size:
            self.buffer.pop(0)
        self.buffer.append({"x": x, "y": y})
        self._save()

    def _save(self):
        try:
            with open(self.buffer_file, "w") as f:
                json.dump(self.buffer, f)
        except Exception as e:
            self.guardian._write_log(f"⚠️ ReplayBuffer save failed: {e}")

    def sample(self, batch_size=32):
        """Return a random batch of samples."""
        import random
        if not self.buffer:
            return None, None
        batch = random.sample(self.buffer, min(batch_size, len(self.buffer)))
        xs = [b["x"] for b in batch]
        ys = [b["y"] for b in batch]
        return (
            torch.tensor(xs, dtype=torch.float32),
            torch.tensor(ys, dtype=torch.float32),
        )

    def size(self):
        return len(self.buffer)


class ContinualTrainer:
    """Periodically retrains NeuralAgent using ReplayBuffer data."""
    def __init__(self, base_path=None):
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)
        self.agent = NeuralAgent(base_path=self.base_path)
        self.buffer = ReplayBuffer(base_path=self.base_path)
        self.guardian._write_log("♻️ ContinualTrainer initialized.")

    def step(self, iterations=10, batch_size=32):
        """Run several small training steps."""
        if self.buffer.size() == 0:
            self.guardian._write_log("ℹ️ ReplayBuffer empty – skipping training.")
            return

        for i in range(iterations):
            x_batch, y_batch = self.buffer.sample(batch_size)
            if x_batch is None:
                break
            loss = self.agent.train_step(x_batch, y_batch)
            if loss is not None:
                self.guardian._write_log(f"🧠 Training step {i+1}/{iterations}, loss={loss:.5f}")

        self.agent.save()
        self.guardian._write_log("✅ ContinualTrainer cycle complete.")

    def auto_train_loop(self, interval=3600):
        """Runs continual training forever in background (hourly by default)."""
        import time
        while True:
            self.guardian.safe_run(self.step)
            time.sleep(interval)


if __name__ == "__main__":
    trainer = ContinualTrainer()
    # Add some synthetic data for testing
    for _ in range(50):
        x = [float(i) for i in range(32)]
        y = [sum(x) / len(x)]
        trainer.buffer.add(x, y)

    trainer.step(iterations=5, batch_size=8)
    print("✅ ContinualTrainer test completed successfully.")

