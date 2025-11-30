"""
Astra Intelligence - Dashboard Cards
------------------------------------
Displays symbol information cards with live data and Astra AI insights.

Features:
• Symbol, price, daily change %
• Volatility and source
• AI Forecast (direction + confidence)
• Astra Rank Score (if available)
• Watchlist support (⭐ / 🗑)
"""

import streamlit as st
import json
from pathlib import Path

WATCHLIST_PATH = Path("astra_watchlist.json")

def render_symbol_card(data_bundle: dict):
    """Render a single symbol card with AI forecast and stats."""

    symbol = data_bundle.get("symbol", "Unknown")
    df = data_bundle.get("df")
    if df is None or df.empty:
        st.warning(f"No data available for {symbol}.")
        return

    latest_price = float(df["close"].iloc[-1])
    prev_price = float(df["close"].iloc[-2]) if len(df) > 1 else latest_price
    change_pct = ((latest_price - prev_price) / prev_price) * 100 if prev_price else 0

    forecast = data_bundle.get("forecast", {})
    direction = forecast.get("forecast_direction", "neutral").capitalize()
    confidence = forecast.get("confidence", 0.0)
    rank_score = data_bundle.get("rank_score", None)
    volatility = data_bundle.get("volatility", None)

    # === Card Layout ===
    st.markdown("---")
    cols = st.columns([2, 2, 2, 2])

    # Symbol & Price
    with cols[0]:
        st.subheader(symbol)
        st.metric("Price", f"${latest_price:.2f}", f"{change_pct:+.2f}%")

    # Rank / Volatility
    with cols[1]:
        if rank_score is not None:
            st.metric("Astra Rank", f"{rank_score:.2f}")
        if volatility is not None:
            st.metric("Volatility", f"{volatility:.2f}")

    # Forecast
    with cols[2]:
        st.metric("AI Forecast", direction, f"{confidence*100:.0f}% conf")

    # Watchlist buttons
    with cols[3]:
        if st.button(f"⭐ Track {symbol}", key=f"track_{symbol}"):
            update_watchlist(symbol, add=True)
        if st.button(f"🗑 Remove", key=f"remove_{symbol}"):
            update_watchlist(symbol, add=False)

def update_watchlist(symbol: str, add: bool = True):
    """Add or remove a symbol from the watchlist."""
    try:
        watchlist = []
        if WATCHLIST_PATH.exists():
            with open(WATCHLIST_PATH, "r") as f:
                watchlist = json.load(f)

        if add and symbol not in watchlist:
            watchlist.append(symbol)
        elif not add and symbol in watchlist:
            watchlist.remove(symbol)

        with open(WATCHLIST_PATH, "w") as f:
            json.dump(watchlist, f, indent=2)

        st.success(f"Watchlist updated: {symbol} {'added' if add else 'removed'}.")

    except Exception as e:
        st.error(f"Failed to update watchlist: {e}")
