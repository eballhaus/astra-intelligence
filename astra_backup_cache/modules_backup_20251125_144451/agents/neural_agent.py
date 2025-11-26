"""
NeuralAgent — Phase-90

Lightweight neural model (logistic regression)
with online learning capability.
"""

import numpy as np


class NeuralAgent:
    def __init__(self, feature_dim=12):
        self.feature_dim = feature_dim

        # Initialize weights
        self.weights = np.zeros(feature_dim)
        self.bias = 0.0

    # ------------------------------------------------------
    # Basic logistic model
    # ------------------------------------------------------
    def sigmoid(self, x):
        try:
            return float(1 / (1 + np.exp(-x)))
        except Exception:
            return 0.5

    def predict(self, vector):
        """vector: numpy array of 12 features."""
        try:
            z = float(np.dot(self.weights, vector) + self.bias)
            return self.sigmoid(z)
        except Exception:
            return 0.5

    # ------------------------------------------------------
    # Training update (for ContinualTrainer)
    # ------------------------------------------------------
    def update(self, vector, label, lr=0.01):
        """
        label: 1 = good outcome, 0 = bad outcome
        Performs one gradient step.
        """
        try:
            pred = self.predict(vector)
            error = (label - pred)

            # gradient update
            self.weights += lr * error * vector
            self.bias += lr * error

        except Exception:
            pass
