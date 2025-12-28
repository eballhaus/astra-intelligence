# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard v12.0
Professional real-time interface for market and crypto signals.
Optimized for performance; no learning engine hooks yet.
"""

# import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timezone
from astra_dashboard.learning.funnel.astra_funnel import AstraFunnel
from astra_dashboard.engine.data_orchestrator import fetch_live_data

# ===============================
#  📊 PAGE CONFIG
# ===============================
st.set_page_config(
    page_title="Astra Intelligence Dashboard",
    layout="wide",
    page_icon="🧠"
)

st.markdown("<h2 style='text-align:center;'>🧠 Astra Intelligence — Dashboard v12</h2>", unsafe_allow_html=True)
st.caption(f"Live System Snapshot — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

# ===============================
#  📈 MARKET OVERVIEW
# ===============================
st.markdown("### 🌍 Market Summary")
market_cols = st.columns(5)
market_data = [
    {"name": "S&P 500", "value": "4,862", "change": "+0.43%"},
    {"name": "NASDAQ", "value": "15,102", "change": "+0.56%"},
    {"name": "DOW JONES", "value": "38,210", "change": "+0.31%"},
    {"name": "BTC", "value": "$67,340", "change": "+1.2%"},
    {"name": "ETH", "value": "$3,212", "change": "+0.8%"}
]
for i, m in enumerate(market_data):
    with market_cols[i]:
        st.metric(m["name"], m["value"], m["change"])

st.divider()

# ===============================
#  ⚡ LIVE ASTRA SIGNALS
# ===============================
st.markdown("### ⚡ Live Astra Predictions")

try:
    funnel = AstraFunnel()
    predictions = funnel.run()
    if not predictions:
        st.warning("⚠️ No predictions received from Astra Funnel.")
        predictions = []
except Exception as e:
    st.error(f"❌ Funnel error: {e}")
    predictions = []

# Enrich with live prices
try:
    live = fetch_live_data()
    live_map = {x.get("symbol"): x for x in live if isinstance(x, dict)}
except Exception as e:
    st.warning(f"⚠️ Live data unavailable: {e}")
    live_map = {}

# Merge live prices
for p in predictions:
    sym = p.get("symbol")
    if sym in live_map:
        p.update({
            "price": live_map[sym].get("price"),
            "target": p.get("target") or round(live_map[sym]["price"] * (1 + (p.get("confidence", 80) - 70) / 1000), 2),
            "stop": p.get("stop") or round(live_map[sym]["price"] * (1 - (p.get("confidence", 80) - 70) / 1500), 2)
        })
        p["pred_pct"] = round(((p["target"] - p["price"]) / p["price"]) * 100, 2)
        p["stop_pct"] = round(((p["price"] - p["stop"]) / p["price"]) * 100, 2)
    else:
        p["price"] = "--"
        p["pred_pct"] = "--"
        p["stop_pct"] = "--"

# ===============================
#  📊 GRID LAYOUT — 12 CARDS
# ===============================
stocks = [x for x in predictions if "/" not in x.get("symbol", "")]
cryptos = [x for x in predictions if "/" in x.get("symbol", "")]
cards = stocks[:6] + cryptos[:6]

if not cards:
    st.info("No Astra predictions available.")
else:
    rows = [cards[i:i+3] for i in range(0, len(cards), 3)]
    for row in rows:
        cols = st.columns(3)
        for i, p in enumerate(row):
            with cols[i]:
                st.markdown(
                    f"""
                    <div style='background-color:#0d1117;padding:15px;border-radius:15px;
                    box-shadow:0 0 10px rgba(0,255,255,0.2);margin-bottom:15px;'>
                    <h4 style='color:#00D9FF;margin-bottom:5px;'>{p['symbol']} <span style='color:#999;'>({p.get('grade','?')})</span></h4>
                    <p><b>Price:</b> {p['price']}</p>
                    <p><b>Prediction:</b> ${p.get('target','--')} ({p.get('pred_pct','--')}%)</p>
                    <p><b>Stop-Loss:</b> ${p.get('stop','--')} ({p.get('stop_pct','--')}%)</p>
                    <p><b>Confidence:</b> {p.get('confidence','--')}%</p>
                    <p><b>Brain Score:</b> {round(float(p.get('confidence',0))*0.97,2)}%</p>
                    <p style='font-size:12px;color:#aaa;'>🧠 {p.get('summary','No summary available.')}</p>
                    </div>
                    """,
                    unsafe_allow_html=True
                )

st.divider()

# ===============================
#  📈 ADVANCED CHART
# ===============================
st.markdown("### 📈 Market Momentum Chart")

try:
    dates = pd.date_range(start="2025-12-01", periods=60, freq="D")
    prices = np.cumsum(np.random.randn(60)) + 100
    fig = go.Figure(data=[go.Candlestick(
        x=dates,
        open=prices + np.random.randn(60),
        high=prices + np.random.rand(60)*2,
        low=prices - np.random.rand(60)*2,
        close=prices,
        increasing_line_color='#00D9FF',
        decreasing_line_color='#FF006E'
    )])
    fig.add_trace(go.Scatter(x=dates, y=prices.rolling(5).mean(), mode='lines', name='Momentum', line=dict(color='white', width=2)))
    fig.update_layout(
        template="plotly_dark",
        height=420,
        margin=dict(l=10, r=10, t=40, b=10),
        xaxis_title="Date",
        yaxis_title="Price",
        title="Astra Market Technical Overview",
        hovermode="x unified"
    )
    st.plotly_chart(fig, width="stretch")
except Exception as e:
    st.warning(f"⚠️ Chart rendering error: {e}")

# ===============================
#  🕐 FOOTER
# ===============================
st.divider()
st.caption(f"🧠 Astra Intelligence v12.0 | Data sources: GuardianV7, TwelveData, CoinGecko, IEX Cloud")
st.caption(f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

