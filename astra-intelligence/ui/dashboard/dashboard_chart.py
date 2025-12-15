# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Chart (Phase 7)
----------------------------------------------
Guardian-logged Plotly candlestick chart with Hydra sentiment overlay.
Supports real + cached data via DataOrchestrator fallback.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

from engine.data_orchestrator import DataOrchestrator
from astra_modules.engine.data_hydra import get_market_sentiment
from core.guardian.guardian_v7 import guardian_log


def _generate_synthetic_data(symbol: str, days: int = 30):
    now = datetime.utcnow()
    base_price = 100.0
    rows = []
    for i in range(days):
        t = now - timedelta(days=days - i)
        o = base_price * (1 + (0.01 * (i % 5)))
        h = o * 1.02
        l = o * 0.98
        c = o * (1 + (0.005 * ((i % 3) - 1)))
        v = 1000 + i * 10
        rows.append([t, o, h, l, c, v])
    df = pd.DataFrame(rows, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["symbol"] = symbol
    return df


def render_chart(symbol: str):
    guardian_log.info(f"[Chart] Rendering chart for {symbol}")
    orchestrator = DataOrchestrator()

    try:
        df = orchestrator.get_live_market_data([symbol])
        if df is None or df.empty or "open" not in df.columns:
            guardian_log.warn(f"[Chart] ⚠️ No live data for {symbol}, using synthetic fallback.")
            df = _generate_synthetic_data(symbol)
        else:
            guardian_log.info(f"[Chart] ✅ Loaded {len(df)} live records for {symbol}")
    except Exception as e:
        guardian_log.error(f"[Chart] ❌ Exception fetching data for {symbol}: {e}")
        df = _generate_synthetic_data(symbol)

    rename_map = {
        "Date": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    }
    df = df.rename(columns=rename_map)
    df = df.sort_values("timestamp")

    try:
        sentiment = get_market_sentiment()
        score = None
        if isinstance(sentiment, dict):
            if symbol in sentiment:
                score = sentiment[symbol].get("score", None)
            elif "fear_greed" in sentiment:
                score = sentiment.get("fear_greed", None)
        guardian_log.info(f"[Chart] Hydra sentiment for {symbol}: {score}")
    except Exception as e:
        guardian_log.warn(f"[Chart] ⚠️ Could not fetch Hydra sentiment: {e}")
        score = None

    fig = go.Figure()

    fig.add_trace(
        go.Candlestick(
            x=df["timestamp"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            name=f"{symbol} Price",
        )
    )

    if score is not None:
        sentiment_line = [score for _ in range(len(df))]
        fig.add_trace(
            go.Scatter(
                x=df["timestamp"],
                y=sentiment_line,
                name="Hydra Sentiment",
                mode="lines",
                line=dict(color="royalblue", width=2, dash="dot"),
                yaxis="y2",
            )
        )
        fig.update_layout(
            yaxis2=dict(
                overlaying="y",
                side="right",
                title="Sentiment",
                range=[0, 1],
                showgrid=False,
            )
        )

    fig.update_layout(
        title=f"{symbol} — Price & Hydra Sentiment",
        xaxis_title="Time",
        yaxis_title="Price (USD)",
        template="plotly_dark",
        height=450,
        margin=dict(l=50, r=50, t=60, b=40),
    )

    refresh = st.button(f"🔄 Refresh {symbol}")
    if refresh:
        st.experimental_rerun()

    st.plotly_chart(fig, use_container_width=True)
    guardian_log.info(f"[Chart] 🧠 Chart rendered for {symbol}")
