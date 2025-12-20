"""
Astra Intelligence – Top 6 Signals Tab
--------------------------------------
Displays AstraPrime’s current top signals as interactive cards.
Each card includes: symbol, trend, confidence, and grade.
Optionally fetches mini price charts via fetch_unified().
"""

import streamlit as st
import pandas as pd
from engine.ranking_engine import (
    get_top_signals,
)  # safely imported core ranking function
from fetch_core.fetch_unified import fetch_unified


def render_signals_tab():
    st.subheader("🚀 Astra Intelligence — Top 6 Ranked Signals")
    st.caption("Powered by AstraPrime Orchestrator & RankingEngine")

    # Attempt to pull top signals
    try:
        signals = get_top_signals()
        if not signals or len(signals) == 0:
            st.warning("No ranked signals available. Please run AstraPrime first.")
            return
    except Exception as e:
        st.error(f"⚠️ Unable to load Top Signals: {e}")
        return

    # Display filters
    cols = st.columns([1, 1])
    with cols[0]:
        min_conf = st.slider("Minimum Confidence", 0.0, 1.0, 0.7, 0.01)
    with cols[1]:
        min_grade = st.selectbox("Minimum Grade", ["C", "B", "B+", "A", "A+"])

    filtered = [
        s
        for s in signals
        if s.get("confidence", 0) >= min_conf and s.get("grade", "C") >= min_grade
    ]

    if not filtered:
        st.info("No signals meet the selected criteria.")
        return

    # Render each signal card
    for sig in filtered[:6]:
        symbol = sig.get("symbol")
        grade = sig.get("grade", "?")
        conf = sig.get("confidence", 0)
        trend = sig.get("trend", "Unknown")

        with st.container(border=True):
            st.markdown(f"### 🪙 {symbol} — Grade {grade}")
            st.metric("🎯 Confidence", f"{conf:.2f}")
            st.markdown(f"**Trend:** {trend}")

            # Mini-chart
            try:
                data = fetch_unified(symbol)
                if isinstance(data, pd.DataFrame) and not data.empty:
                    st.line_chart(data[["close"]].tail(30))
            except Exception as e:
                st.caption(f"⚠️ Chart unavailable for {symbol}: {e}")

            st.divider()

    st.success("✅ Top 6 visualization generated successfully.")
