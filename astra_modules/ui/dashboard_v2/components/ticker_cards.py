import streamlit as st
import requests, json
from pathlib import Path

def fetch_price(symbol: str, api_sources: dict):
    url = api_sources.get("price_api")
    if not url:
        return {"price": "—", "change_pct": "—"}
    try:
        r = requests.get(f"{url}?symbol={symbol}", timeout=3)
        d = r.json()
        return {
            "price": round(d.get("price", 0), 4),
            "change_pct": round(d.get("change_pct", 0), 2)
        }
    except Exception:
        return {"price": "—", "change_pct": "—"}

def render_ticker_section(title: str, symbols: list, api_sources: dict):
    st.subheader(title)
    rows = [symbols[i:i+3] for i in range(0, len(symbols), 3)]
    for row in rows:
        cols = st.columns(len(row))
        for col, sym in zip(cols, row):
            d = fetch_price(sym, api_sources)
            change_color = "🟢" if isinstance(d["change_pct"], (int,float)) and d["change_pct"] > 0 else "🔴"
            col.metric(sym, f"${d['price']}", f"{change_color} {d['change_pct']}%")

def render_ticker_cards(symbols=None, api_sources: dict=None):
    """
    symbols: optional list of tickers to display
    api_sources: dict of API endpoints
    """
    ticker_file = Path("astra_state/ticker_sets.json")
    if ticker_file.exists() and not symbols:
        sets = json.loads(ticker_file.read_text())
        render_ticker_section("🏛 Stocks", sets.get("stocks", []), api_sources)
        render_ticker_section("💠 Crypto", sets.get("crypto", []), api_sources)
    elif symbols:
        render_ticker_section("Selected Tickers", symbols, api_sources)
    else:
        st.warning("Ticker configuration file not found.")
