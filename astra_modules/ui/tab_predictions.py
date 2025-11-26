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
<<<<<<< Updated upstream
<<<<<<< Updated upstream
from astra_modules.chart_core.chart_engine import render_chart_html
=======
=======
>>>>>>> Stashed changes
from astra_modules.chart_core.chart_engine import ChartEngine
from astra_modules.ui.components.ticker_card import render_ticker_card
>>>>>>> Stashed changes
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
        predictions = []
        for symbol in universe_list:
            result = guardian.safe_run(smart_scan, symbol)
            if result:
                predictions.append(result)

    if not predictions:
        st.warning("No predictions available")
        return

    # Split Stocks / Crypto
    stocks = [x for x in predictions if not x.get("ticker", "").endswith("-USD")]
    crypto = [x for x in predictions if x.get("ticker", "").endswith("-USD")]

    selected = st.session_state.get("selected_prediction")
    left, right = st.columns([1.2, 2])

    # LEFT — Stock Table
    with left:
        st.markdown("## 📈 Stocks")
        stock_rows = []
        for x in stocks[:20]:
            stock_rows.append([
                x.get("ticker"),
                round(x.get("rank_score", 0), 3),
                round(x.get("astra_score", 0), 3),
                round(x.get("agent_scores", {}).get("neural", 0), 3),
                round(x.get("agent_scores", {}).get("momentum", 0), 3),
                round(x.get("agent_scores", {}).get("technical", 0), 3),
<<<<<<< Updated upstream
<<<<<<< Updated upstream
                round(x.get("fetch_meta", {}).get("last_price", 0), 3)
=======
                round(x.get("fetch_meta", {}).get("last_price", 0), 3),
>>>>>>> Stashed changes
=======
                round(x.get("fetch_meta", {}).get("last_price", 0), 3),
>>>>>>> Stashed changes
            ])

        df_stocks = pd.DataFrame(
            stock_rows,
            columns=[
<<<<<<< Updated upstream
<<<<<<< Updated upstream
                "Ticker", "Rank Score", "Astra Score",
                "Neural", "Momentum", "Technical", "Price"
            ]
=======
=======
>>>>>>> Stashed changes
                "Ticker",
                "Rank Score",
                "Astra Score",
                "Neural",
                "Momentum",
                "Technical",
                "Price",
            ],
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
        )
        st.dataframe(df_stocks, use_container_width=True, hide_index=True)

        st.markdown("## 🪙 Crypto")
        crypto_rows = []
        for x in crypto[:20]:
            crypto_rows.append([
                x.get("ticker"),
                round(x.get("rank_score", 0), 3),
                round(x.get("astra_score", 0), 3),
                round(x.get("agent_scores", {}).get("neural", 0), 3),
                round(x.get("agent_scores", {}).get("momentum", 0), 3),
                round(x.get("agent_scores", {}).get("technical", 0), 3),
<<<<<<< Updated upstream
<<<<<<< Updated upstream
                round(x.get("fetch_meta", {}).get("last_price", 0), 3)
=======
                round(x.get("fetch_meta", {}).get("last_price", 0), 3),
>>>>>>> Stashed changes
=======
                round(x.get("fetch_meta", {}).get("last_price", 0), 3),
>>>>>>> Stashed changes
            ])

        df_crypto = pd.DataFrame(
            crypto_rows,
            columns=[
<<<<<<< Updated upstream
<<<<<<< Updated upstream
                "Ticker", "Rank Score", "Astra Score",
                "Neural", "Momentum", "Technical", "Price"
            ]
=======
=======
>>>>>>> Stashed changes
                "Ticker",
                "Rank Score",
                "Astra Score",
                "Neural",
                "Momentum",
                "Technical",
                "Price",
            ],
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
        )
        st.dataframe(df_crypto, use_container_width=True, hide_index=True)

    # RIGHT — Chart
    with right:
        st.markdown("## 📊 Prediction Chart")
        if not selected:
            st.info("Select a ticker from the table to display chart.")
            return

        df = guardian.safe_run(universe.fetch_and_clean, selected)
        if df is None:
            st.error("Chart data fetch failed")
            return

    chart_html = guardian.safe_run(render_chart_html, selected, df)
    if chart_html:
        st.components.v1.html(chart_html, height=500, scrolling=False)

