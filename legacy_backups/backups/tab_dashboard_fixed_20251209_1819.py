# ============================================================
# Astra Intelligence Dashboard Tab — Clean Bootstrap Section
# ============================================================

import streamlit as st
import pandas as pd
import traceback

# Guardian Initialization
from astra_core.guardian.guardian_v6 import guardian_boot
from astra_core.guardian import guardian as guardian_log

guardian = getattr(guardian_log, "log", guardian_log)
guardian_boot()

# -------------------------------------------------------------------
# 📦 Dashboard Imports (Safe Load)
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
    print("[Dashboard] ⚠️ Safe load mode activated —", e)
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

st.markdown(
    "<div class='main-title'>🧠 Astra Intelligence — Market Dashboard</div>",
    unsafe_allow_html=True,
)

# -------------------------------------------------------------------
# 🧩 Sidebar
# -------------------------------------------------------------------
try:
    selected_tab = render_sidebar()
except Exception as e:
    guardian.log(f"[Sidebar] ⚠️ Sidebar render failed: {e}")
    st.error(f"⚠️ Sidebar render failed: {e}")
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
        st.warning("⚠️ No valid data available for chart rendering.")
except Exception as e:
    guardian.log(f"[Dashboard] 🚨 Chart rendering failed: {e}")
    st.error(f"🚨 Chart rendering error: {e}")
    traceback.print_exc()

# -------------------------------------------------------------------
# 💠 Symbol Cards & Summary
# -------------------------------------------------------------------
try:
    render_symbol_card(selected_tab, df)
    render_summary(df)
except Exception as e:
    guardian.log(f"[Dashboard] ⚠️ Card or summary render failed: {e}")
    st.error(f"⚠️ Card or summary render failed: {e}")

# -------------------------------------------------------------------
# ✅ Final Status
# -------------------------------------------------------------------
guardian.log("[Dashboard] ✅ Dashboard fully loaded and verified.")
st.success("✅ Dashboard loaded successfully. Guardian protection is active.")

if "df" in locals() and df is not None and not df.empty:
    st.dataframe(df.head())
else:
    st.warning(
        "⚠️ No market data available — try fetching a valid symbol or check your internet connection."
    )
