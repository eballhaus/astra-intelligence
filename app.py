"""
app.py — Phase-60 Astra Intelligence Main Entry
-----------------------------------------------
Handles safe loading of all tabs with automatic session management.
"""

import streamlit as st
from astra_modules.guardian.environment_guardian import safe_import

# -------------------------------------------------------------------
# Page Configuration
# -------------------------------------------------------------------
st.set_page_config(
    page_title="Astra Intelligence — Trading Dashboard",
    layout="wide",
)

# -------------------------------------------------------------------
# Clear session to prevent stale data issues (safe, version-independent)
# -------------------------------------------------------------------
if 'initialized_app' not in st.session_state:
    st.session_state.clear()
    st.session_state.initialized_app = True

# -------------------------------------------------------------------
# Lazy Import Wrapper (prevents startup crashes if a tab fails)
# -------------------------------------------------------------------
def load_tab(name, attr):
    module = safe_import(f"astra_modules.ui.{name}")
    if module is None:
        st.error(f"❌ Failed to load tab module: {name}")
        return None
    return getattr(module, attr, None)

# -------------------------------------------------------------------
# Sidebar Navigation
# -------------------------------------------------------------------
st.sidebar.title("📊 Astra Intelligence")
page = st.sidebar.radio(
    "Navigation",
    ["Dashboard", "Predictions", "Learning Center"],
    index=0
)

# -------------------------------------------------------------------
# ROUTING
# -------------------------------------------------------------------
tab_mapping = {
    "Dashboard": ("tab_dashboard", "render_tab"),
    "Predictions": ("tab_predictions", "render_predictions"),
    "Learning Center": ("tab_learning", "render_learning_center")
}

tab_name, fn_name = tab_mapping[page]
fn = load_tab(tab_name, fn_name)
if fn:
    try:
        fn()
    except Exception as e:
        st.error(f"{page} failed to render: {e}")
