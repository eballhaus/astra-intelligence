# ===============================================================
# Astra 7.0 — Sparkline Component
# Lightweight mini chart for dashboard cards
# ===============================================================

import streamlit as st
import plotly.graph_objects as go
import numpy as np


# ===============================================================
# RENDER SPARKLINE
# ===============================================================

def render_sparkline(series):
    """
    Draws a tiny sparkline chart for the ticker card.
    Input: Pandas Series of close prices (length ~30)
    """

    if series is None or len(series) < 2:
        st.write("—")
        return

    values = series.values.astype(float)

    # Determine color: green if uptrend, red if downtrend
    color = "#26a69a" if values[-1] >= values[0] else "#ef5350"

    fig = go.Figure(
        go.Scatter(
            x=list(range(len(values))),
            y=values,
            mode="lines",
            line=dict(color=color, width=2),
            hoverinfo="skip"
        )
    )

    fig.update_layout(
        height=60,
        width=180,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)"
    )

    st.plotly_chart(fig, use_container_width=False)
