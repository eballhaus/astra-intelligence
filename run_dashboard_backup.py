import os
import sys
# === Astra Intelligence Dashboard Launcher (Safe Mode Compatible) ===
# Works with Streamlit ≥1.28 — prevents RuntimeError: Runtime instance already exists!

import sys
if __name__ == "__main__" and hasattr(sys, "_called_from_test") is False:
    pass  # prevents double Streamlit start


import os, sys
try:
    import streamlit.web.cli as stcli
except ImportError:
    print("Streamlit not found. Activate your venv first.")
    sys.exit(1)

if __name__ == "__main__" and not getattr(stcli, "_is_running_with_streamlit", False):
    sys.argv = ["streamlit", "run", __file__]

# --- Force project root on sys.path and env variable ---
repo_root = os.path.dirname(os.path.abspath(__file__))
if repo_root not in sys.path:
    sys.path.insert(0, repo_root)
os.environ["PYTHONPATH"] = repo_root

# --- Optional debug print ---
print(f"✅ Astra launch root: {repo_root}")

# --- Launch Streamlit dashboard ---
sys.argv = [
    "streamlit",
    "run",
    "astra_modules/ui/dashboard/tab_dashboard.py",
    "--server.headless=true",
]
sys.exit(stcli.main())

