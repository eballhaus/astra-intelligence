"""
NeuralAgent – Astra Intelligence (Phase-100)
--------------------------------------------
Core learning and prediction component for Astra.
Guardian-compatible and designed for continual learning.
"""

import os
import torch
import torch.nn as nn
import torch.optim as optim
from datetime import datetime
from pathlib import Path
import sys

# --- Fix Python path so "astra_modules" can be imported ---
sys.path.append(str(Path(__file__).resolve().parents[2]))
# ----------------------------------------------------------

from astra_modules.guardian.guardian_v6 import GuardianV6


class NeuralAgent(nn.Module):
    def __init__(self, input_size=32, hidden_size=64, output_size=1, base_path=None):
        super().__init__()
        self.base_path = base_path or os.getcwd()
        self.guardian = GuardianV6(self.base_path)

        # Simple feed-forward network
        self.model = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_size)
        )

        self.loss_fn = nn.MSELoss()
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.001)
        self.guardian._write_log("🧠 NeuralAgent initialized.")

    # ----------------------------------------------------------------
    # Training step
    # ----------------------------------------------------------------
    def train_step(self, x_batch, y_batch):
        try:
            self.optimizer.zero_grad()
            y_pred = self.model(x_batch)
            loss = self.loss_fn(y_pred, y_batch)
            loss.backward()
            self.optimizer.step()
            return loss.item()
        except Exception as e:
            self.guardian._write_log(f"⚠️ NeuralAgent training error: {e}")
            return None

    # ----------------------------------------------------------------
    # Prediction
    # ----------------------------------------------------------------
    def predict(self, x):
        with torch.no_grad():
            try:
                return self.model(x)
            except Exception as e:
                self.guardian._write_log(f"⚠️ NeuralAgent prediction error: {e}")
                return torch.zeros_like(x)

    # ----------------------------------------------------------------
    # Save / Load
    # ----------------------------------------------------------------
    def save(self):
        model_dir = Path(self.base_path) / "astra_models"
        model_dir.mkdir(exist_ok=True)
        path = model_dir / "neural_agent.pt"
        torch.save(self.state_dict(), path)
        self.guardian._write_log(f"💾 NeuralAgent saved: {path}")

    def load(self):
        path = Path(self.base_path) / "astra_models" / "neural_agent.pt"
        if path.exists():
            self.load_state_dict(torch.load(path, map_location="cpu"))
            self.guardian._write_log(f"📦 NeuralAgent model loaded from {path}")
        else:
            self.guardian._write_log("⚠️ NeuralAgent model file not found.")


# --------------------------------------------------------------------
# Direct test entry
# --------------------------------------------------------------------
if __name__ == "__main__":
    agent = NeuralAgent()
    x = torch.randn(10, 32)
    y = torch.randn(10, 1)
    for _ in range(5):
        loss = agent.train_step(x, y)
        print(f"Training loss: {loss}")
    agent.save()
    print("✅ NeuralAgent test complete.")

