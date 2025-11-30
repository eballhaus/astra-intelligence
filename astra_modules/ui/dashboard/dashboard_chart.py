"""
Astra Intelligence — Advanced Candle Chart v3 (Syntax-safe)
------------------------------------------------------------
Shows Candles + MA10/30 + Bollinger Bands + RSI + MACD + Momentum
"""

import streamlit as st
import plotly.graph_objects as go
import pandas as pd
import numpy as np


def render_chart(df: pd.DataFrame, symbol: str = ""):
    if df is None or df.empty or "close" not in df.columns:
        st.warning("⚠️ No data available for chart.")
        return None

    try:
        # ──────────────────────────────────────────
        # Indicators
        # ──────────────────────────────────────────
        df = df.copy()
        df["ma_fast"] = df["close"].ewm(span=10).mean()
        df["ma_slow"] = df["close"].ewm(span=30).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["upper"] = df["ma20"] + 2 * df["close"].rolling(20).std()
        df["lower"] = df["ma20"] - 2 * df["close"].rolling(20).std()

        # RSI
        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        # MACD
        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        # Momentum
        df["momentum"] = df["close"] - df["close"].shift(4)

        # ──────────────────────────────────────────
        # Build Plotly figure
        # ──────────────────────────────────────────
        fig = go.Figure()

        # Candles
        fig.add_trace(
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="Candles",
                increasing_line_color="#16A34A",
                decreasing_line_color="#DC2626",
            )
        )

        # MAs
        fig.add_trace(go.Scatter(x=df["date"], y=df["ma_fast"], mode="lines",
                                 name="MA 10", line=dict(width=1.2)))
        fig.add_trace(go.Scatter(x=df["date"], y=df["ma_slow"], mode="lines",
                                 name="MA 30", line=dict(width=1.2, dash="dot")))

        # Bollinger
        fig.add_trace(go.Scatter(x=df["date"], y=df["upper"], mode="lines",
                                 name="BB Upper",
                                 line=dict(color="rgba(255,255,255,0.25)", width=0.8)))
        fig.add_trace(go.Scatter(x=df["date"], y=df["lower"], mode="lines",
                                 name="BB Lower",
                                 line=dict(color="rgba(255,255,255,0.25)", width=0.8),
                                 fill="tonexty",
                                 fillcolor="rgba(255,255,255,0.05)"))

        # Momentum
        fig.add_trace(go.Bar(x=df["date"], y=df["momentum"], name="Momentum",
                             marker_color="rgba(173,216,230,0.4)", yaxis="y2"))

        # RSI
        fig.add_trace(go.Scatter(x=df["date"], y=df["rsi"], name="RSI (14)",
                                 line=dict(color="orange", width=1), yaxis="y3"))

        # MACD
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd"], name="MACD",
                                 line=dict(color="cyan", width=1.5), yaxis="y4"))
        fig.add_trace(go.Scatter(x=df["date"], y=df["macd_signal"], name="Signal",
                                 line=dict(color="magenta", width=1, dash="dot"), yaxis="y4"))

        # ──────────────────────────────────────────
        # Layout
        # ──────────────────────────────────────────
        fig.update_layout(
            height=700,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=40, r=20, t=60, b=40),
            xaxis=dict(showgrid=False, color="#9CA3AF"),
            yaxis=dict(title="Price", color="#E5E7EB"),
            yaxis2=dict(title="Momentum", overlaying="y", side="right",
                        showgrid=False, color="lightblue"),
            yaxis3=dict(title="RSI", overlaying="y", side="left",
                        position=0.02, range=[0, 100], color="orange"),
            yaxis4=dict(title="MACD", overlaying="y", side="right",
                        position=0.98, color="cyan"),
            legend=dict(orientation="h", y=1.02, x=0.5,
                        xanchor="center", font=dict(color="#E5E7EB")),
            title=dict(text=f"📈 {symbol} — Advanced Chart", x=0.5,
                       font=dict(color="#A7F3D0")),
        )

        return fig

    except Exception as e:
        st.error(f"🚨 Chart rendering error: {e}")
        return None
