# -*- coding: utf-8 -*-
"""
dashboard_cards.py — AstraGlass KPI Cards (Scrollable Columns)
--------------------------------------------------------------
Displays stock and crypto performance cards with hover summary
and "Track" button integration.
"""

import streamlit as st
from astra_modules.utils.watchlist_tools import (
    add_to_watchlist, remove_from_watchlist, is_tracked
)


import streamlit as st
import json
from pathlib import Path

WATCHLIST_FILE = Path("/Users/ericballhaus/Desktop/astra-intelligence/astra_watchlist.json")

def render_cards(items, category="stocks"):
    """
    Render interactive cards for Stocks or Crypto assets.
    Supports hover expansion, persistent ⭐ tracking, and 🗑 removal.
    """
    # Load or initialize the watchlist
    if WATCHLIST_FILE.exists():
        with open(WATCHLIST_FILE, "r") as f:
            watchlist = json.load(f)
    else:
        watchlist = {"stocks": [], "crypto": []}

    for item in items:
        symbol = item.get("symbol", "N/A")
        price = item.get("price", 0)
        change = item.get("change", 0.0)
        source = item.get("source", "API")

        color = "#22C55E" if change >= 0 else "#EF4444"
        st.markdown(
            f"""
            <div class="card-hover" style="padding:0.7rem;margin-bottom:0.6rem;border-radius:12px;
                background:rgba(255,255,255,0.04);box-shadow:0 0 8px rgba(0,0,0,0.2);">
                <h4 style="color:#A7F3D0;margin:0;">{symbol}</h4>
                <p style="margin:0;font-size:0.9rem;color:#9CA3AF;">{source}</p>
                <p style="color:{color};font-weight:600;">${price:.2f} ({change:+.2f}%)</p>
            </div>
            """,
            unsafe_allow_html=True,
        )

        # Track / Remove buttons
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button(f"⭐ Track {symbol}", key=f"track_{category}_{symbol}"):
                if symbol not in watchlist[category]:
                    watchlist[category].append(symbol)
                    st.toast(f"✅ {symbol} added to {category} watchlist")

        with col2:
            if st.button(f"🗑 Remove {symbol}", key=f"remove_{category}_{symbol}"):
                if symbol in watchlist[category]:
                    watchlist[category].remove(symbol)
                    st.toast(f"🗑️ {symbol} removed from {category} watchlist")

    # Save updated watchlist
    with open(WATCHLIST_FILE, "w") as f:
        json.dump(watchlist, f, indent=2)
