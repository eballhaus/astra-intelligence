# -----------------------------------------------------------------
# PredictionFusionV2 — weighted fusion using performance_tracker.json
# -----------------------------------------------------------------
import json
import os

import numpy as np


class PredictionFusionV2:
    """Weighted ensemble fusion using learned reliabilities."""

    def __init__(self, agents=None, tracker_path=None, guardian=None):
        self.agents = agents or []
        self.guardian = guardian
        self.tracker_path = tracker_path or os.path.join(
            "astra_modules", "learning", "performance_tracker.json"
        )
        self.weights = self._load_weights()
        if self.guardian:
            self.guardian._write_log(
                "🧠 PredictionFusionV2 (weighted) initialized.")

    def _load_weights(self):
        try:
            with open(self.tracker_path) as f:
                data = json.load(f)
            weights = {k: v["reliability"] for k, v in data.items()}
            total = sum(weights.values()) or 1
            return {k: v / total for k, v in weights.items()}
        except Exception:
            return {}

    def predict(self, x):
        preds, names = [], []
        for i, agent in enumerate(self.agents):
            try:
                y = float(agent.predict(x))
                preds.append(y)
                name = agent.__class__.__name__
                names.append(name)
            except Exception as e:
                print(f"⚠️ {agent.__class__.__name__} error: {e}")

        if not preds:
            return {"signal": 0.0, "confidence": 0.0, "weights": {}}

        preds = np.array(preds)
        weights = np.array(
            [self.weights.get(n, 1 / len(preds)) for n in names], dtype=float
        )
        weights /= weights.sum()

        fused = float(np.dot(preds, weights))
        variance = float(np.var(preds))
        confidence = max(0.0, min(1.0, 1.0 - variance))
        return {
            "signal": fused,
            "confidence": confidence,
            "weights": {n: float(w) for n, w in zip(names, weights)},
        }
