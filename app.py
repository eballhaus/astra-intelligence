"""
Astra Intelligence — Main App Controller (Phase-101.9)
------------------------------------------------------
Handles Streamlit tab navigation between:
 • Dashboard (AstraGlass)
 • Predictions
 • Learning
 • System Guardian
All components are GuardianV6-secured and dynamically loaded.
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
from astra_modules.guardian.guardian_v6 import GuardianV6
guardian = GuardianV6(BASE_DIR)

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
# ===========================================================
with tabs[0]:
    try:
        # ✅ Correct modern import
        from astra_modules.ui.dashboard.tab_dashboard import render_dashboard_tab
        render_dashboard_tab()
    except Exception as e:
        st.error("⚠️ Dashboard tab unavailable.")
        st.warning(str(e))

# ===========================================================
# 📊 Predictions
# ===========================================================
with tabs[1]:
    try:
        from astra_modules.ui.tab_predictions import render_predictions_tab
        render_predictions_tab()
    except Exception as e:
        st.error("⚠️ Predictions tab unavailable.")
        st.warning(str(e))

# ===========================================================
# 📚 Learning
# ===========================================================
with tabs[2]:
    try:
        from astra_modules.ui.tab_learning import render_learning_tab
        render_learning_tab()
    except Exception as e:
        st.error("⚠️ Learning tab unavailable.")
        st.warning(str(e))

# ===========================================================
# 🛡️ System Guardian
# ===========================================================
with tabs[3]:
    try:
        from astra_modules.ui.tab_guardian import render_guardian
        render_guardian()
    except Exception as e:
        st.error("⚠️ Guardian tab unavailable.")
        st.warning(str(e))

# ===========================================================
# Footer
# ===========================================================
st.markdown("<hr style='opacity:0.15;'>", unsafe_allow_html=True)
st.caption("🧠 Astra Intelligence | Phase-101.9 NeuralGlass Dashboard | © 2025")
