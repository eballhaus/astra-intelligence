"""
tab_dashboard.py — Phase-90 (Corrected for YOUR folder structure)

Dashboard:
 • Universe selector
 • Auto-run ScanManager for selected ticker
 • AstraPrime v2 scoring
 • Ticker card preview
 • Interactive chart (ChartEngine)
 • Fully Guardian-safe
"""

import streamlit as st
import pandas as pd

# --------------------------
# Correct imports based on YOUR actual file structure
# --------------------------
from astra_modules.guardian.guardian_v3 import GuardianV3
from astra_modules.universe.universe_builder import UniverseBuilder   # ✔ FIXED
from astra_modules.scanners.scan_manager import ScanManager
from astra_modules.chart_core.chart_engine import ChartEngine
from astra_modules.ui.components.ticker_card import render_ticker_card
from astra_modules.engine.ranking_engine import RankingEngine


def render_dashboard():

    st.markdown(
        "<h1 style='color:#F5F7FA;font-weight:700;'>Astra Intelligence — Dashboard</h1>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='color:#9DA5B4;margin-top:-12px;'>Phase-90 Multi-Agent Engine</p>",
        unsafe_allow_html=True
    )

    guardian = GuardianV3()
    universe = UniverseBuilder()
    scanner = ScanManager()
    chart_engine = ChartEngine()
    ranker = RankingEngine()

    # =================================================================
    # UNIVERSE SELECTION
    # =================================================================
    st.sidebar.header("Market Universe")

    ulist = guardian.safe_run(universe.build_universe)
    if not ulist:
        st.error("Unable to load universe.")
        return

    # Split stocks vs crypto
    stocks = [x for x in ulist if not x.endswith("-USD")]
    crypto = [x for x in ulist if x.endswith("-USD")]

    mode = st.sidebar.radio("Select market:", ["Stocks", "Crypto"])
    options = stocks if mode == "Stocks" else crypto

    symbol = st.sidebar.selectbox("Choose ticker", options)
    if not symbol:
        st.warning("No symbol selected.")
        return

    # =================================================================
    # MAIN SCAN
    # =================================================================
    with st.spinner("Fetching data and running multi-agent scan…"):
        preds = guardian.safe_run(scanner.scan_universe)

    if not preds:
        st.error("Unable to generate predictions.")
        return

    # Find selected ticker
    row = next((x for x in preds if x["ticker"] == symbol), None)
    if not row:
        st.error("Ticker not found in scan results.")
        return

    packet = row["packet"]
    meta = packet.get("fetch_meta", {})

    final_score = packet.get("astra_score", 0)
    grade = packet.get("grade", "?")

    # =================================================================
    # LAYOUT
    # =================================================================
    left, right = st.columns([1.1, 2])

    # LEFT SIDE — TICKER CARD
    with left:
        st.markdown("### 🔍 Overview")
        render_ticker_card(
            symbol=symbol,
            price=meta.get("last_price", 0),
            final_score=final_score,
            buy_score=packet["agent_scores"]["momentum"] * 100,
            confidence=final_score * 100,
            summary=f"Grade: {grade}",
            sparkline=meta.get("sparkline", []),
        )
        st.markdown(
            f"<p style='color:#C4C8CF;font-size:15px;'>"
            f"Astra Score: <b>{final_score:.3f}</b> ({grade})</p>",
            unsafe_allow_html=True
        )

    # RIGHT SIDE — CHART
    with right:
        st.markdown("### 📈 Price Chart")
        df = guardian.safe_run(scanner.fetch_and_clean, symbol)
        if df is None or len(df) < 5:
            st.error("No chart data available.")
        else:
            chart_html = guardian.safe_run(chart_engine.render_chart, symbol, df)
            if chart_html:
                st.components.v1.html(chart_html, height=460, scrolling=False)

    # AGENT DETAILS
    st.markdown("### 🤖 Agent Breakdown")
    st.json(packet["agent_scores"])
