# -*- coding: utf-8 -*-
"""
dashboard_summary.py — Astra Market Overview
--------------------------------------------
Top-level market indices and crypto summary.
"""

from datetime import datetime, timezone

import numpy as np
import pandas as pd
import streamlit as st

try:
    from astra_modules.fetch_core.fetch_unified import fetch_unified
except Exception:
    fetch_unified = None


def _simulate_summary_data():
    """Create simulated market summary data if fetch_unified is unavailable."""
    now = datetime.now(timezone.utc)
    data = {
        "Symbol": ["AAPL", "TSLA", "BTC-USD", "ETH-USD"],
        "Type": ["Stock", "Stock", "Crypto", "Crypto"],
        "Price": np.round([192.5, 238.9, 41000, 2120], 2),
        "Change (%)": np.round(np.random.randn(4) * 2, 2),
        "Volume": np.random.randint(1_000_000, 10_000_000, 4),
        "Updated": [now.strftime("%H:%M:%S")] * 4,
    }
    return pd.DataFrame(data)


def render_summary():
    """Render the market summary section."""
    st.markdown(
        """
        <div style='text-align:center; padding:12px; border-radius:12px;
        background:rgba(255,255,255,0.04); border:1px solid rgba(255,255,255,0.07);
        margin-bottom:12px;'>
            <h2 style='color:#F5F7FA; margin-bottom:0;'>🌐 Astra Market Overview</h2>
            <p style='color:#9DA5B4; margin-top:4px;'>Phase-103 | Aggregated Market Sentiment</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    df = None
    try:
        if fetch_unified:
            df = fetch_unified(
                "AAPL", interval="1d", limit=5
            )  # simple connectivity check
    except Exception:
        df = None

    if df is None or df.empty:
        df = _simulate_summary_data()

    # Format coloring
    def color_change(val):
        color = "lime" if val > 0 else "red"
        return f"color: {color}; font-weight:600;"

    st.dataframe(
        df.style.applymap(
            lambda v: (
                "color: lime; font-weight:600;"
                if isinstance(v, (float, int)) and v > 0
                else ""
            )
        ),
        use_container_width=True,
        height=260,
    )

    st.markdown(
        "<p style='text-align:center;color:#9DA5B4;font-size:0.85em;margin-top:6px;'>"
        "Data provided by Astra Intelligence • Live/Simulated Aggregation Engine"
        "</p>",
        unsafe_allow_html=True,
    )
