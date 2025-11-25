# app.py
# Astra Intelligence Phase-90 Main Application

import os
import streamlit as st
from astra_modules.guardian.guardian_v6 import GuardianV6

# UI tab imports
from astra_modules.ui.tab_dashboard import render_dashboard
from astra_modules.ui.tab_predictions import render_predictions
from astra_modules.ui.tab_learning import render_learning

# Optional: from astra_modules.ui.tab_monitoring import render_monitoring


def main():
    """Launch Astra Intelligence Phase-90 Streamlit application."""

    # ---------- GLOBAL PAGE CONFIG ----------
    st.set_page_config(
        page_title="Astra Intelligence – Phase-90",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ---------- GUARDIAN INITIALIZATION ----------
    base_path = os.path.dirname(os.path.abspath(__file__))
    guardian = GuardianV6(base_path)
    guardian.safe_run(lambda: print(f">>> GuardianV6 initialized at {base_path}"))

    # ---------- SIDEBAR NAVIGATION ----------
    st.sidebar.markdown(
        """
        <h2 style='color:#6FA3EF;'>🧭 Navigation</h2>
        """,
        unsafe_allow_html=True,
    )

    selected_tab = st.sidebar.radio(
        "Select a tab:",
        ["Dashboard", "Predictions", "Learning", "Monitoring"],
        index=0,
    )

    st.sidebar.markdown(
        "<p style='color:#6FA3EF;font-weight:600;'>🛡️ Guardian V6 verified system integrity.</p>",
        unsafe_allow_html=True,
    )

    # ---------- MAIN ROUTING ----------
    if selected_tab == "Dashboard":
        render_dashboard()
    elif selected_tab == "Predictions":
        render_predictions()
    elif selected_tab == "Learning":
        render_learning()
    elif selected_tab == "Monitoring":
        st.info("Monitoring module under development for Phase-100.")
    else:
        st.error("Invalid tab selection.")

    # ---------- FOOTER ----------
    st.markdown(
        """
        <hr>
        <div style='text-align:center;color:#6FA3EF;'>
            © 2025 Astra Intelligence • Phase-90 Framework
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------- ENTRY POINT ----------
if __name__ == "__main__":
    main()

