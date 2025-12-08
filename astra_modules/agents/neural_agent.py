import torch
import torch.nn as nn

from astra_modules.agents.base_agent import BaseAgent


class NeuralNet(nn.Module):
    def __init__(self, input_size=32, hidden_size=64, output_size=1):
        super().__init__()
        self.input_size = input_size
        self.fc1 = nn.Linear(input_size, hidden_size)
        self.relu = nn.ReLU()
        self.fc2 = nn.Linear(hidden_size, output_size)

    def forward(self, x):
        # Convert input to tensor
        if not isinstance(x, torch.Tensor):
            x = torch.tensor(x, dtype=torch.float32)
        x = x.flatten()

        # ✅ If input smaller than expected, pad with zeros
        if x.numel() < self.input_size:
            padding = torch.zeros(self.input_size - x.numel())
            x = torch.cat((x, padding))
        elif x.numel() > self.input_size:
            x = x[: self.input_size]  # truncate safely

        x = x.unsqueeze(0)  # shape: (1, input_size)
        return self.fc2(self.relu(self.fc1(x)))


class NeuralAgent(BaseAgent):
    def __init__(self):
        super().__init__()
        self.model = NeuralNet()
        self.g_log("[NeuralAgent] Model initialized (Guardian-safe)")

    def predict(self, x_input=None):
        try:
            if x_input is None:
                x_input = torch.zeros(32)
            output = self.model(x_input)
            return float(output.squeeze().detach().numpy())
        except Exception as e:
            self.g_log(f"⚠️ Prediction error: {e}")
            return 0.0
