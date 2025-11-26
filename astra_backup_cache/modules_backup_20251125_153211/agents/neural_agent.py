"""
NeuralAgent – Phase-101
-----------------------
A Guardian-protected neural network agent for Astra Intelligence.
Automatically initializes input/output dimensions and logs all events.
"""

import os
import torch
import torch.nn as nn
import torch.optim as optim


class NeuralNet(nn.Module):
    """Lightweight neural network architecture."""

    def __init__(self, input_size=32, hidden_size=64, output_size=1):
        super().__init__()
        self.model = nn.Sequential(
            nn.Linear(input_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, hidden_size),
            nn.ReLU(),
            nn.Linear(hidden_size, output_size),
        )

    def forward(self, x):
        return self.model(x)


class NeuralAgent:
    """Guardian-supervised neural model for Astra."""

    def __init__(self, guardian, input_size=32, hidden_size=64, output_size=1):
        self.guardian = guardian
        self.guardian._write_log("🧠 Initializing NeuralAgent...")
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

        self.model = NeuralNet(input_size, hidden_size, output_size).to(self.device)
        self.optimizer = optim.Adam(self.model.parameters(), lr=0.001)
        self.criterion = nn.MSELoss()

        self.guardian._write_log(f"✅ NeuralAgent initialized on {self.device} (Phase-101).")

    # ------------------------------------------------------------------

    def train_step(self, x_batch, y_batch):
        """Single training step."""
        try:
            x = torch.tensor(x_batch, dtype=torch.float32, device=self.device)
            y = torch.tensor(y_batch, dtype=torch.float32, device=self.device)

            self.optimizer.zero_grad()
            output = self.model(x)
            loss = self.criterion(output, y)
            loss.backward()
            self.optimizer.step()

            loss_val = loss.item()
            self.guardian._write_log(f"📉 Training step complete (loss={loss_val:.6f})")
            return loss_val

        except Exception as e:
            self.guardian._write_log(f"⚠️ Training error: {e}")
            return None

    # ------------------------------------------------------------------

    def predict(self, x_input):
        """Guardian-protected prediction."""
        try:
            x = torch.tensor(x_input, dtype=torch.float32, device=self.device)
            with torch.no_grad():
                output = self.model(x).cpu().numpy().tolist()
            self.guardian._write_log("🧩 Prediction completed.")
            return output
        except Exception as e:
            self.guardian._write_log(f"⚠️ Prediction error: {e}")
            return None

