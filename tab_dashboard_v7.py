# -*- coding: utf-8 -*-
"""
Astra Intelligence - Live Dashboard v10.2
Pulls live data from AstraFunnel and displays top-ranked assets
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from learning.funnel.astra_funnel import AstraFunnel
import numpy as np

# -------------------------------------------------------
# Cached live funnel call (refresh every 15 seconds)
# -------------------------------------------------------
@st.cache_data(ttl=15)
def get_live_predictions():
    try:
        funnel = AstraFunnel()
        preds = funnel.run()
        if not isinstance(preds, list):
            return []
        return preds
    except Exception:
        return []

def render_dashboard():
    st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide", page_icon="🧠")

    # ======================================================
    # 📊 MARKET OVERVIEW
    # ======================================================
    st.markdown("### 📊 Market Overview")
    market_cols = st.columns(4)
    overview = [
        {"name": "S&P 500", "value": "4,862", "change": "+0.43%"},
        {"name": "NASDAQ", "value": "15,102", "change": "+0.56%"},
        {"name": "DOW JONES", "value": "38,210", "change": "+0.31%"},
        {"name": "Bitcoin", "value": "$67,340", "change": "+1.2%"},
    ]
    for i, m in enumerate(overview):
        with market_cols[i]:
            st.metric(label=m["name"], value=m["value"], delta=m["change"])

    st.divider()

    # ======================================================
    # ⚡ LIVE ASTRA SIGNALS
    # ======================================================
    st.markdown("### ⚡ Live Astra Signals")

    predictions = get_live_predictions()
    if not predictions:
        st.warning("⚠️ No live predictions available from AstraFunnel.")
        return

    # rank by confidence × grade weight
    def grade_weight(g):
        return 1.0 if g.startswith("A") else 0.8 if g.startswith("B") else 0.5
    for p in predictions:
        p["score"] = p.get("confidence", 0) * grade_weight(p.get("grade", "C"))

    stocks = sorted(
        [p for p in predictions if "/" not in p.get("symbol", "")],
        key=lambda x: x["score"],
        reverse=True
    )[:6]
    cryptos = sorted(
        [p for p in predictions if "/" in p.get("symbol", "")],
        key=lambda x: x["score"],
        reverse=True
    )[:6]

    col1, col2 = st.columns(2)

    # ---- STOCKS ----
    with col1:
        st.subheader("📈 Stocks")
        if not stocks:
            st.info("No stock predictions available.")
        for s in stocks:
            with st.container(border=True):
                st.markdown(f"**{s.get('symbol','N/A')}** | **{s.get('grade','-')}**")
                st.write(f"💰 Live: ${s.get('price','--')}")
                st.write(f"🎯 Target: ${s.get('target','--')} ({s.get('pred_pct','--')}%)")
                st.write(f"🛑 Stop-Loss: ${s.get('stop','--')} ({s.get('stop_pct','--')}%)")
                conf = s.get('confidence', 0)
                st.progress(conf / 100)
                st.caption(f"🧠 {conf}% confidence | {s.get('summary','Astra signal pending...')}")

    # ---- CRYPTOS ----
    with col2:
        st.subheader("💹 Cryptos")
        if not cryptos:
            st.info("No crypto predictions available.")
        for c in cryptos:
            with st.container(border=True):
                st.markdown(f"**{c.get('symbol','N/A')}** | **{c.get('grade','-')}**")
                st.write(f"💰 Live: ${c.get('price','--')}")
                st.write(f"🎯 Target: ${c.get('target','--')} ({c.get('pred_pct','--')}%)")
                st.write(f"🛑 Stop-Loss: ${c.get('stop','--')} ({c.get('stop_pct','--')}%)")
                conf = c.get('confidence', 0)
                st.progress(conf / 100)
                st.caption(f"🧠 {conf}% confidence | {c.get('summary','Astra signal pending...')}")

    st.divider()

    # ======================================================
    # 📈 ADVANCED CHART
    # ======================================================
    st.subheader("📈 Advanced Market Chart")
    try:
        dates = pd.date_range(start="2025-12-01", periods=60, freq="H")
        prices = 100 + np.cumsum(np.random.randn(60))
        momentum = np.gradient(prices)
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=dates, open=prices - 1, high=prices + 1, low=prices - 2, close=prices,
            increasing_line_color="green", decreasing_line_color="red", name="Price"
        ))
        fig.add_trace(go.Scatter(x=dates, y=momentum, mode="lines", name="Momentum", line=dict(color="orange", width=2)))
        fig.update_layout(
            template="plotly_dark",
            xaxis_title="Time",
            yaxis_title="Price",
            height=420,
            title="Astra Combined Price & Momentum"
        )
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.warning(f"⚠️ Chart rendering error: {e}")

    # ======================================================
    # 🕒 FOOTER
    # ======================================================
    st.divider()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"🧠 Astra Intelligence Dashboard | Last updated: {now}")
    st.caption("Data sources: Guardian • TwelveData • Polygon • CoinGecko • IEX • Alpha Vantage • FinBrain")

if __name__ == "__main__":
    render_dashboard()
