import importlib
import streamlit as st

# --- Reload dashboard modules dynamically to prevent Streamlit cache bugs ---
import astra_core.ui.dashboard.dashboard_sidebar as sidebar
import astra_core.ui.dashboard.dashboard_data as data
import astra_core.ui.dashboard.dashboard_cards as cards
import astra_core.ui.dashboard.dashboard_summary as summary

for mod in (sidebar, data, cards, summary):
    importlib.reload(mod)

# --- Rebind key functions safely ---
render_sidebar = getattr(sidebar, "render_sidebar", None)
load_data = getattr(data, "load_data", None)
render_symbol_card = getattr(cards, "render_symbol_card", None)
render_summary = getattr(summary, "render_summary", None)

# --- Guardian logging ---
from astra_core.guardian.guardian_v6 import guardian_log
guardian = guardian_log("Astra Dashboard initialized safely.")

st.title("Astra Intelligence — Market Dashboard")

# --- Validate functions before proceeding ---
if not all(callable(f) for f in [render_sidebar, load_data, render_symbol_card]):
    guardian.log("One or more dashboard functions not callable — attempting recovery.")
    st.error("Dashboard function load error — please restart Streamlit.")
else:
    try:
        selected_tab = render_sidebar()
        df = load_data(selected_tab)
        render_symbol_card(selected_tab, df)
        render_summary(df)
        st.success("Dashboard loaded successfully. Guardian protection is active.")
    except Exception as e:
        guardian.log(f"Dashboard runtime error: {e}")
        st.error(f"Dashboard initialization failed: {e}")
