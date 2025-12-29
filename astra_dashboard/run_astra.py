"""
run_astra.py  –  Minimal working demo for Astra Intelligence
-------------------------------------------------------------
Loads a small dataset, runs a trivial regression forecast,
computes a dummy harmony score, and prints the result.
"""

import pandas as pd
import numpy as np
from sklearn.linear_model import LinearRegression

from state.planetary_tensor_builder import PlanetaryTensorBuilder
from astra_dashboard.astra_modules.forecast.holistic_model_core import HolisticModelCore
from astra_dashboard.core.harmony_score_calculator import HarmonyScoreCalculator
from astra_dashboard.guardian.alignment_bridge import AlignmentBridge


# ---------- 1. Collect & prepare data ----------
builder = PlanetaryTensorBuilder()

# Here we just create synthetic sample data (replace later with real feeds)
dates = pd.date_range("2025-01-01", periods=30, freq="D")
market = np.linspace(100, 130, 30) + np.random.randn(30) * 2
energy = np.linspace(50, 60, 30) + np.random.randn(30)
climate = np.random.randn(30) * 0.5 + 20
social = np.random.randn(30) * 0.3 + 10

builder.tensor = pd.DataFrame(
    {
        "date": dates,
        "market": market,
        "energy": energy,
        "climate": climate,
        "social": social,
    }
).set_index("date")

print("📊 Data collected:", builder.tensor.head(2), "\n")


# ---------- 2. Analyze patterns ----------
model_core = HolisticModelCore(builder.tensor)

# Simple example: predict 'market' from other variables
X = builder.tensor[["energy", "climate", "social"]]
y = builder.tensor["market"]

reg = LinearRegression().fit(X, y)
model_core.stability_index = float(reg.score(X, y))  # R² score as pseudo-stability
model_core.trend_predictions = {
    "coefficients": reg.coef_.tolist(),
    "intercept": reg.intercept_,
}

print(f"📈 Stability Index: {model_core.stability_index:.3f}")
print("🔍 Coefficients:", model_core.trend_predictions, "\n")


# ---------- 3. Guardian alignment check ----------
guardian = AlignmentBridge()
guardian.audit_forecast(model_core.get_outputs())
guardian.log_alignment_check()
print("🛡️ Guardian check complete.\n")


# ---------- 4. Compute Harmony Score ----------
harmony = HarmonyScoreCalculator()
score = harmony.compute_score(
    model_core.stability_index,
    empathic_metrics=0.85,  # placeholder for Empathic Framework result
)

print(f"🌍 Humanity & Planet Harmony Score: {score:.3f}")
print("✅ Astra demo run complete.")
"""
Astra Intelligence – Phase-90 Launcher
--------------------------------------
Starts Guardian V6 and the Streamlit dashboard from the GitHub-linked
astra-intelligence repository.
"""

import os
import subprocess
import sys
from datetime import datetime

# --- Configuration ----------------------------------------------------------
PROJECT = "/Users/ericballhaus/astra-intelligence"
VENV_PYTHON = "/Users/ericballhaus/astra_env/bin/python3"
APP = os.path.join(PROJECT, "app.py")

# --- Log startup ------------------------------------------------------------
print(f"🔧 Using Python: {VENV_PYTHON}")
print(f"📂 Project: {PROJECT}")
print(f"📄 Launching app: {APP}")

# --- Ensure log directory exists -------------------------------------------
logs_dir = os.path.join(PROJECT, "astra_logs")
os.makedirs(logs_dir, exist_ok=True)
with open(os.path.join(logs_dir, "run_log.txt"), "a") as log:
    log.write(f"Launch at {datetime.now().isoformat()}\n")

# --- Run Streamlit ----------------------------------------------------------
cmd = [
    VENV_PYTHON,
    "-m",
    "streamlit",
    "run",
    APP,
    "--server.headless=false",
    "--browser.gatherUsageStats=false",
]

try:
    subprocess.run(cmd, check=False)
except KeyboardInterrupt:
    print("\n🛑 Astra dashboard stopped by user.")
    sys.exit(0)
except Exception as e:
    print(f"❌ Launch failed: {e}")
    sys.exit(1)
