from astra_dashboard.ui.dashboard.tab_dashboard_v7 import render_dashboard as render_dashboard_tab
import app_bootstrap
# --- Astra Intelligence Permanent Path Bootstrap ---
import os, sys

# Always ensure we are running from the project root, even inside Streamlit subprocesses
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ENGINE_PATH = os.path.join(PROJECT_ROOT, "engine")
if os.getcwd() != PROJECT_ROOT:
    os.chdir(PROJECT_ROOT)

# Guarantee Python can find the main and engine folders
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
if ENGINE_PATH not in sys.path: sys.path.insert(0, ENGINE_PATH)

print(f"[AstraBootstrap] cwd: {os.getcwd()}")
print(f"[AstraBootstrap] sys.path[:3]: {sys.path[:3]}")
# ------------------------------------------------------------
# --- Astra Intelligence Path Bootstrap ---
import os, sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ENGINE_PATH = os.path.join(PROJECT_ROOT, "engine")
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
if ENGINE_PATH not in sys.path: sys.path.insert(0, ENGINE_PATH)
print(f"[AstraBootstrap] Working directory: {os.getcwd()}")
print(f"[AstraBootstrap] sys.path entries:\n  - {PROJECT_ROOT}\n  - {ENGINE_PATH}")
# ------------------------------------------------
# --- Astra Intelligence Path Bootstrap ---
import os, sys
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
ENGINE_PATH = os.path.join(PROJECT_ROOT, "engine")
if PROJECT_ROOT not in sys.path: sys.path.insert(0, PROJECT_ROOT)
if ENGINE_PATH not in sys.path: sys.path.insert(0, ENGINE_PATH)
print(f"[AstraBootstrap] sys.path initialized:")
for p in sys.path[:5]:
    print("  ", p)
# ------------------------------------------------
import sys, os
ROOT = os.path.abspath(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
import sys, os; sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import sys, os; sys.path.append(os.path.abspath(os.path.dirname(__file__)))
"""
Astra Intelligence — Main App Controller (Phase-101.9)
------------------------------------------------------
Handles Streamlit tab navigation between:
 • Dashboard (AstraGlass)
 • Predictions
 • Learning
 • System Guardian
All components are GuardianV7-secured and dynamically loaded.
"""

import streamlit as st
import os
import sys

# ──────────────────────────────────────────────
# Path setup
# ──────────────────────────────────────────────
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
astra_path = os.path.join(BASE_DIR, "astra_modules")
if astra_path not in sys.path:
    sys.path.insert(0, astra_path)

# ──────────────────────────────────────────────
# Guardian Import
# ──────────────────────────────────────────────
from astra_modules.guardian.guardian_v6 import GuardianV7

guardian = GuardianV7()

# ──────────────────────────────────────────────
# Streamlit Base Config
# ──────────────────────────────────────────────
st.set_page_config(
    page_title="Astra Intelligence | NeuralGlass",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Global Styles (NeuralGlass)
# ──────────────────────────────────────────────
st.markdown(
    """
    <style>
    body { background-color:#0F172A; color:#F5F7FA; }
    section.main > div { padding-top:1rem; padding-bottom:1rem; }
    .stTabs [data-baseweb="tab-list"] { gap:12px; }
    .stTabs [data-baseweb="tab"] {
        background-color:rgba(255,255,255,0.05);
        border-radius:12px;


        padding:10px 16px;
        font-weight:500;
        color:#E5E7EB;
    }
    .stTabs [aria-selected="true"] {
        background-color:rgba(56,189,248,0.15);
        border:1px solid rgba(56,189,248,0.25);
        color:#38BDF8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Header
# ──────────────────────────────────────────────
st.markdown(
    """
    <div style='text-align:center;margin-bottom:20px;'>
        <h1 style='color:#F5F7FA;margin-bottom:0;'>🌌 Astra Intelligence</h1>
        <p style='color:#9DA5B4;margin-top:0;'>Phase-101.9 NeuralGlass | Guardian V6 Active</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────
# Tabs
# ──────────────────────────────────────────────
tabs = st.tabs(["Dashboard", "Predictions", "Learning", "System Guardian"])

# ===========================================================
# 🧠 Dashboard
import importlib.util, sys, os
dash_path = os.path.join(os.path.dirname(__file__), "ui", "dashboard", "tab_dashboard.py")
spec = importlib.util.spec_from_file_location("tab_dashboard", dash_path)
tab_dashboard = importlib.util.module_from_spec(spec)
sys.modules["tab_dashboard"] = tab_dashboard
from astra_dashboard.ui.dashboard.tab_dashboard_v7 import render_dashboard as render_dashboard_tab

# ===========================================================

# ===========================================================
# 📊 Predictions
# ===========================================================
with tabs[1]:
        from ui.tab_predictions import render_predictions_tab

        render_predictions_tab()
        st.error("⚠️ Predictions tab unavailable.")

# ===========================================================
# 🧠 Dashboard (Clean Import)
with tabs[0]:
    render_dashboard_tab()

