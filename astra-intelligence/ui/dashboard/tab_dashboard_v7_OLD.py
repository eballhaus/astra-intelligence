from ui.dashboard.dashboard_chart import render_chart
from engine.data_hydra import get_market_sentiment
import sys, os; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
import sys, os; sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
"""

import sys, os
sys.path.append(os.path.expanduser("~/Desktop/astra-intelligence"))
Integrates Hydra Sentiment, Funnel Ranking, Guardian V7, and Brain Context.
"""

import streamlit as st
import pandas as pd
from engine.data_orchestrator import DataOrchestrator
from engine.data_funnel import select_top_assets as get_top_assets
from engine.data_orchestrator import DataOrchestrator

def render_dashboard():

    orchestrator = DataOrchestrator()

    # Sidebar
    st.sidebar.header("Dashboard Controls")
    trade_mode = st.sidebar.selectbox("Mode", ["Day Trading", "Swing Trading"])
    refresh = st.sidebar.button("🔄 Refresh Data")

    if refresh:
        st.toast("Fetching latest market data...", icon="🔄")
        time.sleep(0.5)

    # Hydra Sentiment
    with st.container():
        st.subheader("🧠 Market Sentiment (Hydra Layer)")
        sentiment = get_market_sentiment()
        st.metric("Global Sentiment", sentiment.get("summary", "Neutral"))
        st.metric("Fear/Greed Index", sentiment.get("fear_greed", "—"))
        st.caption(f"Updated {sentiment.get('timestamp', 'now')}")

    # Funnel Rankings
    st.subheader("📊 Top 6 Assets by Momentum & Volatility")
    top_assets = get_top_assets()
    df_assets = pd.DataFrame(top_assets)
    st.dataframe(df_assets, use_container_width=True)

    # Charts
    st.subheader("📈 Price & Sentiment Charts")
    for _, row in df_assets.iterrows():
        st.markdown(f"#### {row['symbol']}")
        render_chart(row["symbol"])

    # Brain Insights
    st.subheader("🧩 Contextual AI Insights")
    for symbol in df_assets["symbol"].head(3):
        insight = contextual_insight(symbol)
        st.write(f"**{symbol}** → {insight}")

    # Guardian Log
    st.subheader("🛡️ Guardian V7 System Health")
    logs = guardian_log.get_recent_events(10)
    for log in logs:
        st.text(f"[{log['timestamp']}] {log['level']}: {log['message']}")

    st.success("✅ Hydra Dashboard Ready — All modules operational.")
