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
