"""
Wrapper for chart rendering.
Handles error messages and clean Streamlit display.
"""

import streamlit as st
from astra_modules.chart_core.chart_engine import render_chart

def chart_container(symbol: str):
    if not symbol:
        st.info("Select a symbol from the left panels to load the chart.")
        return

    st.plotly_chart(render_chart(symbol), use_container_width=True)
