import streamlit as st
import numpy as np

# ============================================================
# ASTRA MINI CHART — SPARKLINE SVG (Neon Line)
# ============================================================

def render_mini_chart(data_points):
    """
    Renders a sparkline (inline SVG) inside the glass ticker card.
    """

    if not data_points or len(data_points) < 2:
        st.markdown("<div class='astra-mini-chart'>No chart data</div>", unsafe_allow_html=True)
        return

    arr = np.array(data_points, dtype=float)

    y_min, y_max = float(arr.min()), float(arr.max())
    if y_max - y_min == 0:
        normalized = np.zeros_like(arr)
    else:
        normalized = (arr - y_min) / (y_max - y_min)

    normalized = 1 - normalized  # Flip vertical

    # Chart dimensions
    width = 140
    height = 40
    step = width / (len(normalized) - 1)

    # Convert to "x,y" format
    points = " ".join(f"{i * step},{normalized[i] * height}" for i in range(len(arr)))

    # Color based on trend
    trend_color = "#3CEE72" if arr[-1] >= arr[0] else "#FF4E4E"

    svg = f"""
    <svg width="{width}" height="{height}" xmlns="http://www.w3.org/2000/svg"
         class="astra-mini-chart">
        <polyline
            fill="none"
            stroke="{trend_color}"
            stroke-width="2.2"
            stroke-linecap="round"
            stroke-linejoin="round"
            points="{points}"
        />
    </svg>
    """

    st.markdown(svg, unsafe_allow_html=True)
