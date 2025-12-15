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

# --- Phase7 Compatibility Patch ---
try:
    from astra_core.ui.dashboard.tab_dashboard import render_tab as render_dashboard_tab
except Exception:
    def render_dashboard_tab(*args, **kwargs):
        import streamlit as st; st.warning('⚠️ Dashboard tab temporarily unavailable.'); return None


# --- Phase7.5 Dashboard Restoration ---
def render_dashboard_tab():
    """Phase-7.5 Streamlit Dashboard Renderer."""
    import streamlit as st
    from astra_core.guardian.guardian_v6 import GuardianV6

    st.title("📊 Astra Intelligence — NeuralGlass Dashboard")
    st.caption("Phase-7.5 | FastBoot Engine + Guardian V6 Active")

    try:
        guardian = GuardianV6()
        status = getattr(guardian, "status", "Unknown")
        st.success(f"Guardian Status: {status}")
    except Exception as e:
        st.warning(f"Guardian not fully initialized: {e}")

    st.divider()
    st.info("Overview: Data systems operational — awaiting live market data stream.")
