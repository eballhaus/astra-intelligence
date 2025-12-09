# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Main Tab (v7)
--------------------------------------------
The primary Streamlit dashboard layout and orchestration file.
Now includes Guardian integration and automatic dashboard integrity verification.

Features:
✅ One-time Guardian integrity check
✅ Streamlit-safe layout (no duplicate widgets)
✅ Dynamic sidebar integration
✅ Resilient data fetch and fallback protection
✅ Guardian event logging for every UI load
"""

import os
import streamlit as st
import pandas as pd
import traceback

# -------------------------------------------------------------------
# 🔒 Guardian Integration
# -------------------------------------------------------------------
from astra_core.guardian.guardian_v6 import guardian_log
from astra_core.ui.dashboard.dashboard_guardian import ensure_dashboard_integrity

guardian = guardian_log()
guardian.log("[Dashboard] 🚀 Initializing Astra Intelligence Dashboard Tab...")

# Prevent Streamlit from triggering the integrity check multiple times
if "dashboard_checked" not in st.session_state:
    ensure_dashboard_integrity()
    st.session_state["dashboard_checked"] = True

# -------------------------------------------------------------------
# 📦 Dashboard Imports
# -------------------------------------------------------------------
try:
    from astra_core.ui.dashboard import (
        render_sidebar,
        render_chart,
        load_data,
        render_symbol_card,
        render_summary,
    )
except Exception as e:
    guardian.log(f"[Dashboard] 🚨 Failed to import dashboard components: {e}")
    st.error("⚠️ Dashboard components failed to load.")
    st.stop()

# -------------------------------------------------------------------
# 🎨 UI Layout Setup
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Astra Intelligence Dashboard",
    layout="wide",
    page_icon="🧠",
)

st.markdown(
    """
    <style>
    body {
        background-color: #0b0f17;
        color: #e5e7eb;
        font-family: 'Inter', sans-serif;
    }
    .main-title {
        font-size: 2rem;
        font-weight: 600;
        color: #A7F3D0;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown("<div class='main-title'>🧠 Astra Intelligence — Market Dashboard</div>", unsafe_allow_html=True)

# -------------------------------------------------------------------
# 🧩 Sidebar
# -------------------------------------------------------------------
try:
    selected_tab = render_sidebar()
except Exception as e:
    guardian.log(f"[Sidebar] ⚠️ Sidebar render failed: {e}")
    st.error(f"⚠️ Sidebar error: {e}")
    selected_tab = "Overview"

# -------------------------------------------------------------------
# 📊 Data Loading
# -------------------------------------------------------------------
try:
    df = load_data(selected_tab)
    if df is None or df.empty:
        st.warning("⚠️ No data available to display.")
        guardian.log("[Dashboard] ⚠️ Empty dataset returned from load_data().")
except Exception as e:
    guardian.log(f"[Dashboard] ⚠️ Data load error: {e}")
    st.error(f"⚠️ Data load error: {e}")
    df = pd.DataFrame()

# -------------------------------------------------------------------
# 📈 Chart Section
# -------------------------------------------------------------------
try:
    if not df.empty:
        render_chart(df, symbol=selected_tab)
    else:
        st.warning("⚠️ No valid data for chart rendering.")
except Exception as e:
    guardian.log(f"[Dashboard] 🚨 Chart rendering failed: {e}")
    st.error(f"🚨 Chart rendering error: {e}")
    traceback.print_exc()

# -------------------------------------------------------------------
# 💠 Symbol Cards & Summary
# -------------------------------------------------------------------
try:
    render_symbol_card(selected_tab)
    render_summary(df)
except Exception as e:
    guardian.log(f"[Dashboard] ⚠️ Card or summary render failed: {e}")
    st.error(f"⚠️ Card or summary section error: {e}")

# -------------------------------------------------------------------
# ✅ Final Status
# -------------------------------------------------------------------
guardian.log("[Dashboard] ✅ Dashboard fully loaded and verified.")
st.success("🧠 Astra Intelligence Dashboard is active and Guardian-protected.")
