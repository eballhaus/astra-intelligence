"""
Astra Intelligence - Chart Engine (Phase-90 Compatibility Layer)
---------------------------------------------------------------
This restores the ChartEngine interface expected by older UI modules,
wrapping Streamlit chart rendering around Astra's dataframes.
"""

import streamlit as st
import pandas as pd


class ChartEngine:
    """
    Legacy ChartEngine wrapper to maintain compatibility with older Astra dashboards.
    Uses Streamlit's built-in charting functions to visualize pandas data.
    """

    def __init__(self):
        self.active = True
        st.write("✅ ChartEngine initialized (LightweightChart backend).")

    def render_chart(self, data, title="Astra Chart", chart_type="line"):
        """
        Renders a chart safely using Streamlit. Accepts pandas DataFrame or list-like data.
        """
        if data is None:
            st.warning("⚠️ No data provided to ChartEngine.")
            return

        st.subheader(title)

        if isinstance(data, pd.DataFrame):
            if chart_type == "line":
                st.line_chart(data)
            elif chart_type == "bar":
                st.bar_chart(data)
            elif chart_type == "area":
                st.area_chart(data)
            else:
                st.line_chart(data)
        else:
            st.write(data)

        st.caption(f"{title} – rendered via ChartEngine compatibility layer.")

