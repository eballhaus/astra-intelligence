# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Layout
-------------------------------------
Three-section interface:
Left: Stocks
Middle: Crypto
Right: Advanced Chart
"""

import streamlit as st
from astra_modules.ui.dashboard import (
    dashboard_data,
    dashboard_cards,
    dashboard_chart,
    dashboard_sidebar,
    dashboard_summary,
)
from astra_modules.ui.dashboard.theme_loader import load_theme

# ----------------------------
# 🌌 Astra Intelligence Dashboard
# ----------------------------

st.set_page_config(
    page_title="🧠 Astra Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Load Astra theme
load_theme()

# Header
st.markdown(
    """
    <h1 style='text-align:center; color:#A7F3D0; font-weight:700;'>
        🧠 Astra Intelligence Dashboard
    </h1>
    <p style='text-align:center; color:#9CA3AF;'>
        Autonomous AI-driven Market Intelligence System
    </p>
    <hr style="margin-top:1rem;margin-bottom:1.5rem;border-color:rgba(255,255,255,0.1);">
    """,
    unsafe_allow_html=True,
)

# Sidebar controls
dashboard_sidebar.render_sidebar()

# Symbols
symbols_stocks = ["AAPL", "MSFT", "TSLA", "GOOG", "AMZN", "NVDA"]
symbols_crypto = ["BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "DOGE/USD", "ADA/USD"]

# Fetch data
with st.spinner("Loading market data..."):
    stock_data = {sym: dashboard_data.load_data(sym) for sym in symbols_stocks}
    crypto_data = {sym: dashboard_data.load_data(sym) for sym in symbols_crypto}

# Define layout
left_col, mid_col, right_col = st.columns([1.2, 1.2, 2.6], gap="large")

# ----------------------------
# LEFT COLUMN – STOCKS
# ----------------------------
with left_col:
    st.markdown("### 📊 Stocks Overview")
    st.markdown("<hr>", unsafe_allow_html=True)

    # Scrollable container for stocks
    st.markdown(
        """
        <div style="height: 600px; overflow-y: auto; padding-right: 10px;">
        """,
        unsafe_allow_html=True,
    )

    for sym in symbols_stocks:
        df = stock_data.get(sym)
        if df is None or df.empty:
            dashboard_cards.render_empty_card(sym)
        else:
            dashboard_cards.render_symbol_card(sym, df, include_reason=False)

    st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------
# MIDDLE COLUMN – CRYPTO
# ----------------------------
with mid_col:
    st.markdown("### 💎 Crypto Overview")
    st.markdown("<hr>", unsafe_allow_html=True)

    # Scrollable container for crypto
    st.markdown(
        """
        <div style="height: 600px; overflow-y: auto; padding-right: 10px;">
        """,
        unsafe_allow_html=True,
    )

    for sym in symbols_crypto:
        df = crypto_data.get(sym)
        if df is None or df.empty:
            dashboard_cards.render_empty_card(sym)
        else:
            dashboard_cards.render_symbol_card(sym, df, include_reason=False)

    st.markdown("</div>", unsafe_allow_html=True)

# ----------------------------
# RIGHT COLUMN – ADVANCED CHART
# ----------------------------
with right_col:
    st.markdown("### 📈 Advanced Chart")
    st.markdown("<hr>", unsafe_allow_html=True)

    # Clickable symbol selector
    active_symbol = st.session_state.get("active_symbol", "AAPL")

    df_chart = stock_data.get(active_symbol)
    if df_chart is None or df_chart.empty:
        df_chart = crypto_data.get(active_symbol)

    if df_chart is not None and not df_chart.empty:
        chart = dashboard_chart.render_chart(df_chart, symbol=active_symbol)
        if chart is not None:
            st.plotly_chart(chart, use_container_width=True, config={"displayModeBar": False})
        else:
            st.warning("⚠️ Chart rendering failed.")
    else:
        st.warning("⚠️ No data available for chart. Check API keys or symbol configuration.")

# ----------------------------
# Footer Summary
# ----------------------------
st.markdown("<hr>", unsafe_allow_html=True)
dashboard_summary.render_summary()

st.markdown(
    """
    <p style='text-align:center; color:#6B7280; font-size:0.9rem; margin-top:1rem;'>
        Astra Intelligence © 2025 — NeuralGlass Interface v3.0
    </p>
    """,
    unsafe_allow_html=True,
)
