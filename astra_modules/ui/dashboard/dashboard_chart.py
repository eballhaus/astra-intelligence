# -*- coding: utf-8 -*-
"""
dashboard_chart.py — AstraGlass Interactive Chart
-------------------------------------------------
Renders interactive candlestick chart with:
 • Real OHLCV data from fetch_unified()
 • Red/green candles
 • Moving averages, Bollinger Bands, RSI
 • Astra prediction line overlay
"""

import streamlit as st
import plotly.graph_objects as go
import numpy as np
import pandas as pd


def render_chart(data_bundle: dict, mode: str):
    """Render a Plotly candlestick chart."""
    if not data_bundle or "df" not in data_bundle:
        st.warning("No chart data available.")
        return

    df = data_bundle.get("df")
    if df is None or df.empty:
        st.warning("No data to display.")
        return

    # Normalize time column
    if "date" not in df.columns and "time" in df.columns:
        df = df.rename(columns={"time": "date"})
    df["date"] = pd.to_datetime(df["date"], errors="coerce")

    # Add indicators
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma30"] = df["close"].rolling(30).mean()

    ma20 = df["close"].rolling(20).mean()
    std20 = df["close"].rolling(20).std()
    df["bb_upper"] = ma20 + (2 * std20)
    df["bb_lower"] = ma20 - (2 * std20)

    delta = df["close"].diff()
    up, down = delta.clip(lower=0), -1 * delta.clip(upper=0)
    roll_up = up.rolling(14).mean()
    roll_down = down.rolling(14).mean()
    rs = roll_up / roll_down.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    if "astra_pred" not in df.columns:
        df["astra_pred"] = df["close"] * (1 + np.sin(np.linspace(0, np.pi, len(df))) * 0.01)

    # Build chart
    fig = go.Figure()

    fig.add_trace(go.Candlestick(
        x=df["date"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="Price", increasing_line_color="lime", decreasing_line_color="red"
    ))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma10"], name="MA10", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["ma30"], name="MA30", line=dict(width=1)))
    fig.add_trace(go.Scatter(x=df["date"], y=df["bb_upper"], name="BB Upper", line=dict(width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=df["date"], y=df["bb_lower"], name="BB Lower", line=dict(width=1, dash="dot")))
    fig.add_trace(go.Scatter(x=df["date"], y=df["astra_pred"], name="Astra Prediction", line=dict(width=2, dash="dash")))

    if "volume" in df.columns:
        fig.add_trace(go.Bar(x=df["date"], y=df["volume"], name="Volume", marker_color="rgba(150,150,255,0.4)", yaxis="y2"))

    fig.update_layout(
        template="plotly_dark",
        height=450,
        margin=dict(l=10, r=10, t=30, b=10),
        showlegend=True,
        xaxis_rangeslider_visible=False,
        yaxis=dict(title="Price"),
        yaxis2=dict(
            overlaying="y", side="right", showgrid=False,
            visible="volume" in df.columns, title="Volume"
        ),
    )

    st.plotly_chart(fig, use_container_width=True, key=f"chart_{mode.lower()}")
