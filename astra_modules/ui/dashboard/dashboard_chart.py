"""
Astra Intelligence - Dashboard Chart
------------------------------------
Main visualization component for Astra’s dashboard.
Renders interactive Plotly charts using live OHLCV data and Astra forecasts.

Features:
• Candlestick chart (100 days)
• MA10, MA30, Bollinger Bands, RSI
• Forecast overlay from forecast_engine
• Auto handling of missing data
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from astra_modules.chart_core.plotly_theme import apply_plotly_theme

def render_chart(data_bundle: dict, mode: str = "default"):
    """
    Render the main Astra dashboard chart for the given symbol.
    Accepts a data_bundle from dashboard_data.load_dashboard_data().
    """

    if not data_bundle or "df" not in data_bundle:
        st.warning("No data available to display chart.")
        return

    df = data_bundle["df"]
    if df is None or df.empty:
        st.warning("No price data found for this symbol.")
        return

    # Ensure datetime conversion
    if "date" not in df.columns:
        if "time" in df.columns:
            df.rename(columns={"time": "date"}, inplace=True)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    symbol = data_bundle.get("symbol", "Unknown")

    # === Technical Indicators ===
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA30"] = df["close"].rolling(30).mean()

    df["BB_MID"] = df["MA10"]
    df["BB_STD"] = df["close"].rolling(10).std()
    df["BB_UPPER"] = df["BB_MID"] + 2 * df["BB_STD"]
    df["BB_LOWER"] = df["BB_MID"] - 2 * df["BB_STD"]

    # RSI Calculation
    delta = df["close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df["RSI"] = 100 - (100 / (1 + rs))

    # === Plotly Figure ===
    fig = go.Figure()

    # Candlestick
    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Price",
        increasing_line_color="#00FF88",
        decreasing_line_color="#FF4444",
        showlegend=True
    ))

    # Moving Averages
    fig.add_trace(go.Scatter(x=df["date"], y=df["MA10"],
                             line=dict(color="#FFD700", width=1.5),
                             name="MA10"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["MA30"],
                             line=dict(color="#00BFFF", width=1.5),
                             name="MA30"))

    # Bollinger Bands
    fig.add_trace(go.Scatter(x=df["date"], y=df["BB_UPPER"],
                             line=dict(color="rgba(255,255,255,0.2)", width=1),
                             name="Bollinger Upper"))
    fig.add_trace(go.Scatter(x=df["date"], y=df["BB_LOWER"],
                             line=dict(color="rgba(255,255,255,0.2)", width=1),
                             fill="tonexty",
                             name="Bollinger Lower"))

    # === Astra Forecast Overlay ===
    forecast = data_bundle.get("forecast")
    if forecast and isinstance(forecast, dict):
        direction = forecast.get("forecast_direction", "neutral").capitalize()
        conf = forecast.get("confidence", 0.0)
        st.markdown(
            f"**Astra Forecast:** {direction} ({conf*100:.0f}% confidence)",
            unsafe_allow_html=True
        )

        # Optional visual overlay (if provided)
        if "forecast_line" in forecast:
            forecast_line = forec_
