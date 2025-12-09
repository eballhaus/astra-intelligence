# astra_modules/chart_core/chart_engine.py

"""
Astra Intelligence - Chart Engine (v2)
-------------------------------------
Modular chart builder for all Astra dashboards and agents.
Generates Plotly candlestick charts with:
• OHLCV data
• Moving Averages (MA10, MA30)
• Bollinger Bands
• RSI indicator
• Forecast overlay (optional)
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from astra_core.chart_core.plotly_theme import apply_plotly_theme


# ======================================================
# Helper: Technical Indicators
# ======================================================
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA, Bollinger Bands, and RSI columns."""
    df = df.copy()
    df["MA10"] = df["close"].rolling(10).mean()
    df["MA30"] = df["close"].rolling(30).mean()

    # Bollinger Bands
    df["BB_MID"] = df["MA10"]
    df["BB_STD"] = df["close"].rolling(10).std()
    df["BB_UPPER"] = df["BB_MID"] + 2 * df["BB_STD"]
    df["BB_LOWER"] = df["BB_MID"] - 2 * df["BB_STD"]

    # RSI (14)
    delta = df["close"].diff()
    gain = np.where(delta > 0, delta, 0)
    loss = np.where(delta < 0, -delta, 0)
    avg_gain = pd.Series(gain).rolling(14).mean()
    avg_loss = pd.Series(loss).rolling(14).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    df["RSI"] = 100 - (100 / (1 + rs))
    return df


# ======================================================
# Core Chart Builder
# ======================================================
def build_candlestick_chart(
    df: pd.DataFrame,
    symbol: str = "",
    include_forecast: bool = True,
    forecast_df: pd.DataFrame | None = None,
) -> go.Figure:
    """
    Build an Astra-style candlestick chart with overlays.
    """

    if df is None or df.empty:
        raise ValueError("No OHLCV data available for chart rendering.")

    df = add_indicators(df)
    fig = go.Figure()

    # Candlestick trace
    fig.add_trace(
        go.Candlestick(
            x=df["date"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name="Price",
            increasing_line_color="#00ff88",
            decreasing_line_color="#ff4444",
        )
    )

    # Moving Averages
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["MA10"],
            line=dict(width=1.5, color="#FFD700"),
            name="MA10",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["MA30"],
            line=dict(width=1.5, color="#1E90FF"),
            name="MA30",
        )
    )

    # Bollinger Bands
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["BB_UPPER"],
            line=dict(width=1, color="rgba(173,216,230,0.4)"),
            name="Bollinger Upper",
            hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=df["date"],
            y=df["BB_LOWER"],
            line=dict(width=1, color="rgba(173,216,230,0.4)"),
            fill="tonexty",
            fillcolor="rgba(173,216,230,0.1)",
            name="Bollinger Lower",
            hoverinfo="skip",
        )
    )

    # Forecast Overlay (optional)
    if include_forecast and forecast_df is not None and not forecast_df.empty:
        fig.add_trace(
            go.Scatter(
                x=forecast_df["date"],
                y=forecast_df["forecast"],
                line=dict(width=2, dash="dot", color="#FF00FF"),
                name="Astra Forecast",
            )
        )

    # Layout styling
    fig.update_layout(
        title=f"{symbol} — Astra Intelligence Chart",
        xaxis_title="Date",
        yaxis_title="Price",
        template="plotly_dark",
        height=600,
        margin=dict(l=40, r=40, t=60, b=40),
    )

    apply_plotly_theme(fig)
    return fig
