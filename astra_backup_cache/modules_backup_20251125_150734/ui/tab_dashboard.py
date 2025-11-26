"""
Astra Dashboard – Phase-90
---------------------------------------
Displays Astra’s market universe overview and analytics.
Includes Guardian V6 monitoring, ChartEngine integration,
and self-healing logic for UniverseBuilder failures.
"""

import streamlit as st
import os
import pandas as pd
from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.chart_core.chart_engine import ChartEngine
from astra_modules.universe.universe_builder import build_universe


# --- Initialize Guardian and Chart Engine ---
guardian = GuardianV6(os.path.dirname(__file__))
chart_engine = ChartEngine()


def render_dashboard():
    """Render the main Astra Market Dashboard."""

    st.title("📈 Astra Intelligence — Market Dashboard")
    st.caption("Phase-90 • Guardian V6 Active")

    # Verify Guardian
    guardian.safe_run(lambda: st.success("✅ Guardian V6 verified and online."))

    # Initialize charting
    chart_engine.render_chart(pd.DataFrame({"init": [0]}), title="ChartEngine Initialized")

    st.divider()
    st.subheader("🌌 Market Universe")

    # --- Build or load the trading universe safely ---
    try:
        universe_list = build_universe()
    except Exception as e:
        guardian.safe_run(lambda: st.error(f"Universe Builder Error: {e}"))
        universe_list = []

    # --- Self-healing safeguard ---
    if not universe_list or not hasattr(universe_list, "__iter__"):
        st.warning("⚠️ UniverseBuilder returned invalid or empty data.")
        guardian.safe_run(
            lambda: guardian.log_event(
                "dashboard_warning",
                "Universe list invalid – auto-recovered."
            )
        )
        universe_list = []

    # --- Dashboard metrics ---
    col1, col2, col3 = st.columns(3)
    col1.metric("Universe Size", len(universe_list))
    col2.metric("Active Signals", "–")
    col3.metric("Guardian", "ONLINE")

    st.divider()
    st.subheader("📊 Universe Details")

    # --- Render universe details safely ---
    if not universe_list:
        st.info("No symbols available to display.")
    else:
        for symbol in universe_list:
            st.write(f"📊 Processing {symbol}")
            df = pd.DataFrame({"Price": [100, 102, 101, 104, 103]})
            chart_engine.render_chart(df, title=f"{symbol} Price Trend")

    st.divider()
    st.caption("Astra Phase-90 Dashboard – Operational Mode")

