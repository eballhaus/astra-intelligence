"""
Opportunity Panels — Stocks + Crypto Split Layout (Astra Intelligence)
Uses compact ticker cards + Astra theme.
"""

import streamlit as st
from astra_modules.ui.components.ticker_card import render_ticker_card


def _section_header(title: str, subtitle: str = ""):
    """
    Renders a consistent section header.
    """
    st.markdown(f"""
        <div style="margin-bottom: 8px;">
            <div style="font-size:20px; font-weight:700; color:#F5F7FA;">{title}</div>
            <div style="font-size:14px; color:#9DA5B4;">{subtitle}</div>
        </div>
    """, unsafe_allow_html=True)


def _render_grid(items: list):
    """
    Renders ticker cards in a 3×2 responsive grid.
    """
    if not items:
        st.write("No opportunities available.")
        return

    cols = st.columns(3)
    col_idx = 0

    for item in items:
        with cols[col_idx]:
            render_ticker_card(item)
        col_idx = (col_idx + 1) % 3


def render_split_opportunities(stock_items: list, crypto_items: list):
    """
    Main split layout:
        LEFT  (65%) → Stocks
        RIGHT (35%) → Crypto
    """

    left, right = st.columns([0.65, 0.35])

    # -------------------------
    # STOCKS (LEFT SIDE)
    # -------------------------
    with left:
        _section_header("📈 Top Stock Opportunities",
                        "SmartScan + HybridScan scoring (Top 6)")

        _render_grid(stock_items)

    # -------------------------
    # CRYPTO (RIGHT SIDE)
    # -------------------------
    with right:
        _section_header("💰 Top Crypto Opportunities",
                        "SmartScan + HybridScan scoring (Top 6)")

        # 2×3 grid for crypto
        cols = st.columns(2)
        col_idx = 0

        for item in crypto_items:
            with cols[col_idx]:
                render_ticker_card(item)
            col_idx = (col_idx + 1) % 2
