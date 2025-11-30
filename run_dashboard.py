#!/usr/bin/env python3
"""
Safe Astra Dashboard Launcher
Runs diagnostics first; only launches Streamlit if all checks pass.
"""

import subprocess, sys

print("🧠 Running Astra Diagnostics...\n")
result = subprocess.run([sys.executable, "astra_diagnostics.py"])

if result.returncode == 0:
    print("\n✅ Diagnostics passed — launching Streamlit dashboard...\n")
    subprocess.run([sys.executable, "-m", "streamlit", "run", "astra_modules/ui/dashboard/tab_dashboard.py"])
else:
    print("\n🚨 Diagnostics failed — fix issues before launching dashboard.")
