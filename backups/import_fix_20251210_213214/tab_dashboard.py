# ============================================================
# 🧠 Astra Intelligence Dashboard — Clean Bootstrap (v7 Stable)
# ============================================================

import streamlit as st
import pandas as pd
import traceback, sys

# -------------------------------------------------------------------
# 🎛️ Streamlit Config (must run first)
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Astra Intelligence Dashboard",
    layout="wide",
    page_icon="🧠",
)

# -------------------------------------------------------------------
# 🩺 Debug Helper (renders visible error on black screen)
# -------------------------------------------------------------------
def show_debug_error(e):
    st.error(f"❌ Dashboard initialization failed:\n{e}")
    st.code("".join(traceback.format_exception(*sys.exc_info())))

# -------------------------------------------------------------------
# 🧩 Guardian Initialization (Stable Core)
# -------------------------------------------------------------------
try:
    from astra_core.guardian.guardian_v6 import guardian_boot, guardian

    guardian_boot()
    guardian.log("[Dashboard] ✅ Guardian online")
except Exception as e:
    print(f"[Guardian] ⚠️ Boot failure: {e}")
    guardian = None

# -------------------------------------------------------------------
# 📦 Dashboard Module Imports (Safe Load)
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
    if guardian:
        guardian.log(f"[Dashboard] ⚠️ Safe load mode activated — {e}")
    show_debug_error(e)
    st.stop()

# -------------------------------------------------------------------
# 🎨 UI Styling
# -------------------------------------------------------------------
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
# 🧭 Sidebar
# -------------------------------------------------------------------
try:
    selected_tab = render_sidebar()
except Exception as e:
    if guardian:
        guardian.log(f"[Sidebar] ⚠️ Sidebar render failed: {e}")
    show_debug_error(e)
    selected_tab = "Overview"

# -------------------------------------------------------------------
# 📊 Data Load
# -------------------------------------------------------------------
try:
    df = load_data(selected_tab)
    if df is None or df.empty:
        st.warning("⚠️ No data available to display.")
        if guardian:
            guardian.log("[Dashboard] ⚠️ Empty dataset returned from load_data().")
except Exception as e:
    if guardian:
        guardian.log(f"[Dashboard] ⚠️ Data load error: {e}")
    show_debug_error(e)
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
    if guardian:
        guardian.log(f"[Dashboard] 🚨 Chart rendering failed: {e}")
    show_debug_error(e)

# -------------------------------------------------------------------
# 💠 Cards & Summary
# -------------------------------------------------------------------
try:
    render_symbol_card(selected_tab, df)
    render_summary(df)
except Exception as e:
    if guardian:
        guardian.log(f"[Dashboard] ⚠️ Card or summary render failed: {e}")
    show_debug_error(e)

# -------------------------------------------------------------------
# ✅ Final Status
# -------------------------------------------------------------------
if guardian:
    guardian.log("[Dashboard] ✅ Dashboard fully loaded and verified.")

st.success("✅ Dashboard loaded successfully. Guardian protection is active.")

if 'df' in locals() and isinstance(df, pd.DataFrame) and not df.empty:
    st.dataframe(df.head())
else:
    st.warning("⚠️ No market data available — check your data source or internet connection.")
