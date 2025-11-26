"""
ContinualTrainer – Phase-101
----------------------------
Guardian-supervised continual learning manager for Astra Intelligence.
Supports incremental updates using ReplayBuffer and NeuralAgent.
"""

import os
import random
import torch
import torch.nn as nn
from collections import deque


class ReplayBuffer:
    """Simple replay buffer for continual learning."""

    def __init__(self, capacity=5000):
        self.buffer = deque(maxlen=capacity)

    def add(self, x, y):
        self.buffer.append((x, y))

    def sample(self, batch_size=32):
        batch = random.sample(self.buffer, min(len(self.buffer), batch_size))
        x, y = zip(*batch)
        return list(x), list(y)

    def size(self):
        return len(self.buffer)


class ContinualTrainer:
    """Handles Guardian-protected continual training."""

    def __init__(self, guardian, agent=None):
        self.guardian = guardian
        self.agent = agent
        self.buffer = ReplayBuffer()
        self.guardian._write_log("📚 ContinualTrainer initialized (Phase-101).")

        # Fill buffer with synthetic samples for testing
        for _ in range(100):
            x = [random.random() for _ in range(32)]
            y = [sum(x) / len(x)]
            self.buffer.add(x, y)

    # ------------------------------------------------------------------

    def step(self, iterations=5, batch_size=32):
        """Run incremental learning for a number of iterations."""
        self.guardian._write_log(f"🚀 ContinualTrainer step started ({iterations} iterations).")

        if not self.agent:
            self.guardian._write_log("⚠️ No agent provided – skipping training.")
            return

        if self.buffer.size() == 0:
            self.guardian._write_log("⚠️ ReplayBuffer empty – no training data available.")
            return

        for i in range(iterations):
            x_batch, y_batch = self.buffer.sample(batch_size)
            loss = self.agent.train_step(x_batch, y_batch)
            if loss is not None:
                self.guardian._write_log(f"📉 Iteration {i+1}/{iterations}: loss={loss:.6f}")
            else:
                self.guardian._write_log(f"⚠️ Iteration {i+1}/{iterations} failed – skipping.")

        self.guardian._write_log("✅ ContinualTrainer step completed successfully.")

