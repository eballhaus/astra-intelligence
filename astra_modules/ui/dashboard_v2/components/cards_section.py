import pandas as pd
import streamlit as st

from astra_modules.ui.dashboard_v2 import data_hooks
from astra_modules.ui.dashboard_v2.components.dashboard_cards import (
    render_empty_card, render_symbol_card)

# --- Stock and Crypto lists (Astra can later auto-pick top 6 of each) ---
STOCKS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "GOOGL"]
CRYPTOS = ["BTCUSD", "ETHUSD", "SOLUSD", "AVAXUSD", "BNBUSD", "ADAUSD"]


def render_cards_section():
    """Render Stocks and Crypto cards in two responsive columns with live data."""
    st.subheader("💹 Live Intelligence Cards")

    # Fetch latest prices
    data = data_hooks.get_live_data()
    df = pd.DataFrame(data.get("price_data", []))

    # --- STOCKS ---
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🏛 Stocks")
        for sym in STOCKS:
            row = df[df["symbol"] == sym]
            if not row.empty:
                render_symbol_card(sym, row)
            else:
                render_empty_card()

    # --- CRYPTO ---
    with col2:
        st.markdown("### 💠 Crypto")
        for sym in CRYPTOS:
            row = df[df["symbol"] == sym]
            if not row.empty:
                render_symbol_card(sym, row)
            else:
                render_empty_card()
