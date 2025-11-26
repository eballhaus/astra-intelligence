"""
PredictionFusion – Astra Intelligence (Phase-100C)
--------------------------------------------------
Combines predictions from multiple NeuralAgents and
outputs a single consensus forecast under GuardianV6.
"""

import os
import sys
import torch
from pathlib import Path
from statistics import mean, stdev

# --- Fix Python import path so "astra_modules" is accessible ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# --------------------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.agents.neural_agent import NeuralAgent


class PredictionFusion:
    """
    Loads and manages multiple NeuralAgents for ensemble predictions.
    """
    def __init__(self, base_path=None, ensemble_size=3):
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)
        self.agents = []
        self.ensemble_size = ensemble_size
        self._init_agents()
        self.guardian._write_log("🤖 PredictionFusion initialized.")

    def _init_agents(self):
        for i in range(self.ensemble_size):
            agent = NeuralAgent(base_path=self.base_path)
            agent.load()
            self.agents.append(agent)

    def predict(self, x):
        """Fuse multiple model outputs into a consensus forecast."""
        preds = []
        for idx, agent in enumerate(self.agents):
            try:
                with torch.no_grad():
                    y = agent.predict(x)
                    preds.append(y.squeeze().tolist())
            except Exception as e:
                self.guardian._write_log(f"⚠️ Agent {idx} prediction failed: {e}")

        if not preds:
            return torch.zeros((x.shape[0], 1))

        # Convert list of lists → tensor
        preds_tensor = torch.tensor(preds)
        avg_pred = preds_tensor.mean(dim=0).unsqueeze(1)
        return avg_pred

    def evaluate_consistency(self, x):
        """Optional: measure variance between agent outputs."""
        preds = []
        for agent in self.agents:
            y = agent.predict(x)
            preds.append(y.squeeze().tolist())

        if len(preds) < 2:
            return {"mean": 0.0, "std": 0.0}

        flat_preds = [p for sub in preds for p in (sub if isinstance(sub, list) else [sub])]
        return {
            "mean": float(mean(flat_preds)),
            "std": float(stdev(flat_preds)),
        }


# -------------------------------------------------------------------
# Direct test entry
# -------------------------------------------------------------------
if __name__ == "__main__":
    pf = PredictionFusion()
    x = torch.randn(5, 32)

    fused_pred = pf.predict(x)
    consistency = pf.evaluate_consistency(x)

    print("🔮 Fused prediction output:")
    print(fused_pred)
    print(f"📊 Consistency metrics: mean={consistency['mean']:.4f}, std={consistency['std']:.4f}")
    print("✅ PredictionFusion test completed successfully.")

