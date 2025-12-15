# ============================================================
# Astra Intelligence — Dashboard Summary & Metrics (Stable)
# ============================================================
"""
Consolidates performance summaries and metric cards for Astra dashboard.
Pulls from loaded DataFrame and live APIs via fetch_unified.
"""

import streamlit as st
import pandas as pd
from astra_core.guardian.guardian_v6 import guardian


guardian.log("[DashboardSummary] ✅ Summary module active.")


def render_symbol_card(symbol: str, df: pd.DataFrame):
    """Render a top-level summary card for a symbol."""
    if df is None or df.empty:
        st.warning("⚠️ No data available for this symbol.")
        return

    latest = df.iloc[-1]
    price = latest.get("close", 0)
    change = df["close"].pct_change().iloc[-1] * 100 if len(df) > 1 else 0

    col1, col2 = st.columns(2)
    with col1:
        st.metric(label=f"{symbol} Price", value=f"${price:,.2f}")
    with col2:
        st.metric(label="Change (24h)", value=f"{change:+.2f}%")


def render_summary(df: pd.DataFrame):
    """Render an overview summary section."""
    if df is None or df.empty:
        st.info("📭 No summary data available.")
        return

    avg_price = df["close"].mean()
    high = df["high"].max()
    low = df["low"].min()
    vol = df["volume"].sum()

    st.subheader("📊 Market Summary")
    st.write(f"**Average Price:** ${avg_price:,.2f}")
    st.write(f"**High:** ${high:,.2f} | **Low:** ${low:,.2f}")
    st.write(f"**Volume:** {vol:,.0f}")

    guardian.log("[DashboardSummary] ✅ Summary rendered successfully.")
