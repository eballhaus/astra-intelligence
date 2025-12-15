import streamlit as st
from astra_modules.ui.dashboard_v2.components.cards_section import render_cards_section
from astra_modules.ui.dashboard_v2.components.advanced_chart import render_advanced_chart
from astra_modules.ui.dashboard_v2 import data_hooks
import pandas as pd

def render_layout(data=None):
    st.title("🧠 Astra Intelligence — Dashboard 2.1")

    # --- Live card section (two columns) ---
    render_cards_section()

    # --- Advanced Chart (optional) ---
    st.header("📈 Forecast & Market Chart")
    hist = data.get("history", {}).get("AAPL") if data else None
    if hist:
        df = pd.DataFrame(hist)
        render_advanced_chart(df)
    else:
        st.info("No chart data yet — live data still loading.")
