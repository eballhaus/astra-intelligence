"""
tab_predictions.py — Phase-90

Predictions Tab:
 • Auto-run smart_scan
 • RankingEngine integration
 • Stocks + Crypto tables
 • Click-to-view chart
 • Guardian-safe
"""

import streamlit as st
import pandas as pd

from astra_modules.guardian.guardian_v6 import GuardianV6 as GuardianV3
from astra_modules.scanners.smart_scan import smart_scan
from astra_modules.chart_core.chart_engine import ChartEngine
from astra_modules.ui.components.ticker_card import render_ticker_card
from astra_modules.engine.ranking_engine import RankingEngine
from astra_modules.universe.universe_builder import UniverseBuilder


def render_predictions():
    st.markdown(
        "<h1 style='color:#F5F7FA;font-weight:700;'>Astra Intelligence — Predictions</h1>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<p style='color:#9DA5B4;margin-top:-12px;'>Phase-90 Multi-Agent Engine</p>",
        unsafe_allow_html=True,
    )

    guardian = GuardianV3()
    chart_engine = ChartEngine()
    ranker = RankingEngine()
    universe = UniverseBuilder()

    # ================================
    # RUN SMART SCAN
    # ================================
    universe_list = guardian.safe_run(universe.build_universe)
    if not universe_list:
        st.error("Universe load failed")
        return

    with st.spinner("Running smart scan across universe…"):
        # Call smart_scan() for each symbol; collect results
        predictions = []
        for symbol in universe_list:
            result = guardian.safe_run(smart_scan, symbol)
            if result:
                predictions.append(result)

    if not predictions:
        st.warning("No predictions available")
        return

    # Split Stocks / Crypto
    stocks = [x for x in predictions if not x["ticker"].endswith("-USD")]
    crypto = [x for x in predictions if x["ticker"].endswith("-USD")]

    selected = st.session_state.get("selected_prediction")

    left, right = st.columns([1.2, 2])

    # LEFT — Stock Table
    with left:
        st.markdown("## 📈 Stocks")
        stock_rows = [
            [
                x.get("ticker"),
                round(x.get("rank_score", 0), 3),
                round(x.get("astra_score", 0), 3),
                round(x.get("agent_scores", {}).get("neural", 0), 3),
                round(x.get("agent_scores", {}).get("momentum", 0), 3),
                round(x.get("agent_scores", {}).get("technical", 0), 3),
                round(x.get("fetch_meta", {}).get("last_price", 0), 3),
            ]

