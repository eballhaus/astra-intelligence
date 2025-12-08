import os
import sys
import streamlit.web.cli as stcli

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

