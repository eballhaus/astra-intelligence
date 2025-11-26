"""
replay_buffer.py — Phase-90 Upgrade
Stores structured learning experiences for Astra’s hybrid learning loop:
(state → prediction → outcome)
Safe, stable, and fully compatible with ContinualTrainer + NeuralAgent.
"""

from collections import deque
import random


class ReplayBuffer:
    def __init__(self, capacity: int = 5000):
        """
        capacity: maximum stored experiences.
        Oldest entries are automatically discarded.
        """
        self.buffer = deque(maxlen=capacity)

    # ==================================================================
    # ADD EXPERIENCE
    # ==================================================================
    def add(self, state, prediction, outcome):
        """
        Stores one complete learning sample.

        Expected structure:
            state = { "features": [...] }
            prediction = float
            outcome = float  (PnL or reward)
        """

        try:
            # Ensure state exists
            safe_state = state.copy() if isinstance(state, dict) else {}

            # Guarantee standardized feature vector
            if "features" not in safe_state:
                safe_state["features"] = [0.0] * 8

            exp = {
                "state": safe_state,
                "prediction": float(prediction),
                "outcome": float(outcome)
            }

            self.buffer.append(exp)

        except Exception as e:
            print(f"[ReplayBuffer] Error adding experience: {e}")

    # ==================================================================
    # SAMPLE BATCH
    # ==================================================================
    def sample(self, batch_size: int = 64):
        """
        Randomly samples training data.

        If buffer is smaller than batch size,
        return everything (safe fallback).
        """
        try:
            if len(self.buffer) == 0:
                return []

            if len(self.buffer) <= batch_size:
                return list(self.buffer)

            return random.sample(self.buffer, batch_size)

        except Exception as e:
            print(f"[ReplayBuffer] Error during sampling: {e}")
            return []
