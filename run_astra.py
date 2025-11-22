import os
import subprocess
import sys

PROJECT = "/Users/ericballhaus/Desktop/ai_trading_dashboard"
VENV_PYTHON = f"{PROJECT}/venv/bin/python3"

APP = f"{PROJECT}/app.py"

print("🔧 Using Python:", VENV_PYTHON)
print("📂 Project:", PROJECT)
print("📄 Launching app:", APP)

cmd = [VENV_PYTHON, "-m", "streamlit", "run", APP, "--server.headless", "false"]

subprocess.run(cmd)
