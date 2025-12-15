# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Main Tab (Phase 5)
-------------------------------------------------
Orchestrates Sidebar, Data Loader, and Orchestrator for live Astra display.
"""
import sys, os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../../")))

import streamlit as st
from ui.dashboard.dashboard_sidebar import render_sidebar
from ui.dashboard.dashboard_data import load_data
from engine.data_orchestrator import DataOrchestrator

st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide")

selected_tab = render_sidebar()
orchestrator = DataOrchestrator()

st.title("🚀 Astra Intelligence Dashboard")
st.caption("Guardian v7 — Live Mode")

if selected_tab == "Overview":
    symbols = ["AAPL", "TSLA", "BTC/USD", "ETH/USD", "SPY", "NVDA"]
    df_live = orchestrator.get_live_market_data(symbols)
    if df_live is not None and not df_live.empty:
        st.dataframe(df_live)
    else:
        st.warning("⚠️ No live data available.")

elif selected_tab == "Markets":
    df = load_data("AAPL")
    if df is not None and not df.empty:
        st.line_chart(df[["timestamp", "close"]].set_index("timestamp"))
    else:
        st.warning("⚠️ Unable to load market data.")

elif selected_tab == "Crypto":
    df = load_data("BTC/USD")
    if df is not None and not df.empty:
        st.line_chart(df[["timestamp", "close"]].set_index("timestamp"))
    else:
        st.warning("⚠️ Unable to load crypto data.")

elif selected_tab == "AI Insights":
    st.info("🧠 Coming soon — Astra AI Forecast Integration.")

elif selected_tab == "Settings":
    st.success("⚙️ Customize themes and preferences in the sidebar.")
