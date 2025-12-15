import streamlit as st
import pandas as pd
import plotly.express as px

def render_charts(data: dict):
    try:
        df = pd.DataFrame(data.get("forecast_data", []))
        if df.empty:
            st.warning("No forecast data to display.")
            return
        fig = px.line(df, x="timestamp", y="prediction", title="Forecast vs Actual")
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Chart rendering error: {e}")
