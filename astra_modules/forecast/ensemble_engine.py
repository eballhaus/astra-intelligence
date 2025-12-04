"""
ensemble_engine.py
──────────────────────────────────────────────────────────────────
Astra Intelligence — EnsembleEngine (Phase 2.2)
Aggregates multiple agent scores into a unified ensemble forecast.

Design Goals:
- Simple, deterministic, and explainable aggregation logic
- Defensive normalization and weighting
- Compatible with ForecastEngine v3 (Hybrid Ensemble)
- Configurable weighting and confidence computation

Module Version: v1.0.0
Author: Astra Intelligence Team
"""

from __future__ import annotations
import math
import numpy as np
from typing import Dict, Any, Callable


# ──────────────────────────────────────────────
# Type Aliases
# ──────────────────────────────────────────────
AgentFunction = Callable[[str, Dict[str, Any]], float]


class EnsembleEngine:
    """
    Combines outputs from multiple scoring agents
    (momentum, technical, volume, risk, psychology, neural)
    into a unified ensemble score and confidence metric.
    """

    def __init__(self, agents: Dict[str, AgentFunction], weights: Dict[str, float] | None = None):
        """
        Args:
            agents:  dict of agent name → callable (symbol, data) → float [-1, 1]
            weights: optional dict of agent name → float weight (unnormalized)
        """
        self.agents = agents
        self.weights = weights or {name: 1.0 for name in agents}
        self._normalize_weights()

    # ──────────────────────────────────────────────
    # Internal Helpers
    # ──────────────────────────────────────────────
    def _normalize_weights(self) -> None:
        total = sum(abs(w) for w in self.weights.values()) or 1.0
        for k in self.weights:
            self.weights[k] = self.weights[k] / total

    @staticmethod
    def _safe_clip(value: float) -> float:
        """Clamps score into [-1, 1]."""
        if math.isnan(value) or math.isinf(value):
            return 0.0
        return max(-1.0, min(1.0, value))

    # ──────────────────────────────────────────────
    # Core Computation
    # ──────────────────────────────────────────────
    def score(self, symbol: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Computes weighted mean of agent scores and overall confidence.
        
        Returns:
            {
              "symbol": str,
              "scores": {agent: score},
              "ensemble_score": float,
              "confidence": float (0–1)
            }
        """
        raw_scores: Dict[str, float] = {}
        for name, fn in self.agents.items():
            try:
                s = self._safe_clip(float(fn(symbol, data)))
            except Exception:
                s = 0.0
            raw_scores[name] = s

        # Weighted mean aggregation
        w_scores = np.array([raw_scores[a] * self.weights.get(a, 1.0) for a in raw_scores])
        ensemble_score = float(np.sum(w_scores))

        # Confidence = 1 − normalized variance of agent scores
        std = float(np.std(list(raw_scores.values())))
        confidence = float(max(0.0, min(1.0, 1 - std)))  # low variance → high confidence

        return {
            "symbol": symbol.upper(),
            "scores": raw_scores,
            "ensemble_score": round(self._safe_clip(ensemble_score), 4),
            "confidence": round(confidence, 4),
        }

    # ──────────────────────────────────────────────
    # Diagnostics / Utility
    # ──────────────────────────────────────────────
    def set_weights(self, weights: Dict[str, float]) -> None:
        """Update weights and re-normalize."""
        self.weights.update(weights)
        self._normalize_weights()

    def get_status(self) -> Dict[str, Any]:
        """Returns engine diagnostic state."""
        return {
            "agents": list(self.agents.keys()),
            "weights": self.weights,
            "active_agents": len(self.agents),
        }

    def __repr__(self) -> str:
        return f"<EnsembleEngine agents={len(self.agents)}, weights={list(self.weights.keys())}>"
