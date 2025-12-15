import sys, os
import streamlit as st

# Add the current working directory to sys.path
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Confirm the file exists (for safety)
expected_path = os.path.join(PROJECT_ROOT, "ui", "dashboard", "tab_dashboard_v7.py")
if not os.path.exists(expected_path):
    st.error(f"Dashboard file not found: {expected_path}")
    raise SystemExit(1)

# Import the dashboard module
from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title="Astra Intelligence — Hydra Dashboard", layout="wide")
render_dashboard()
