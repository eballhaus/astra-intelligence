# ──────────────────────────────────────────────
# Astra Intelligence Sidebar (Phase-105)
# AstraGlass Neural Interface
# ──────────────────────────────────────────────

import streamlit as st

from astra_modules.ui.dashboard.theme_loader import apply_theme


def render_sidebar(active_tab: str = "Dashboard"):
    """
    Render the Astra Intelligence sidebar with navigation.
    Phase-105 version — theme handled globally by theme_loader.
    """
    # Apply Astra theme (safeguard in case Streamlit re-renders)
    apply_theme()

    # Sidebar header
    st.sidebar.markdown(
        """
        <div style='text-align:center;padding:12px;'>
            <h2 style='color:#5EEAD4;'>🧠 Astra Intelligence</h2>
            <p style='color:#9DA5B4;font-size:0.9em;'>NeuralGlass Interface</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Navigation links
    tabs = ["Dashboard", "Analytics", "Settings"]
    selected_tab = st.sidebar.radio(
        "Navigation", tabs, index=tabs.index(active_tab))

    # Visual separator
    st.sidebar.markdown("<hr>", unsafe_allow_html=True)

    # Guardian / System Info
    st.sidebar.markdown(
        """
        <div style='text-align:center; padding-top:8px;'>
            <p style='font-size:0.9em; color:#94A3B8;'>
                🛡️ Astra Guardian V6 Active<br>
                <span style='color:#5EEAD4;'>System Secure ✅</span>
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    return selected_tab
