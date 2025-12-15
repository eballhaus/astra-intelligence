import streamlit as st

from astra_modules.ui.dashboard_v2.data_hooks import get_live_data
from astra_modules.ui.dashboard_v2.layout import render_layout

st.set_page_config(
    page_title="Astra Intelligence Dashboard 2.0", layout="wide")

st.title("🧠 Astra Intelligence — Dashboard 2.0")
st.markdown(
    "Real-time engine orchestration, forecasting, and Guardian telemetry.")

# Pull data from Astra's orchestrator brain
data = get_live_data()

# Render full dashboard layout
render_layout(data)
