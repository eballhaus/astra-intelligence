"""
Astra Intelligence — Market Overview (No yfinance)
Fetches live market indices and BTC using public APIs.
"""

from datetime import datetime

import requests
import streamlit as st


@st.cache_data(ttl=900)
def fetch_market_data():
    data = {}
    try:
        yahoo_url = (
            "https://query1.finance.yahoo.com/v7/finance/quote"
            "?symbols=^DJI,^GSPC,^IXIC"
        )
        res = requests.get(yahoo_url, timeout=5)
        res.raise_for_status()
        quotes = res.json().get("quoteResponse", {}).get("result", [])
        for q in quotes:
            symbol = q.get("symbol", "")
            data[symbol] = {
                "price": q.get("regularMarketPrice", 0),
                "change": q.get("regularMarketChangePercent", 0),
            }
        btc = requests.get(
            "https://api.coingecko.com/api/v3/simple/price"
            "?ids=bitcoin&vs_currencies=usd&include_24hr_change=true",
            timeout=5,
        ).json()["bitcoin"]
        data["BTC-USD"] = {"price": btc["usd"], "change": btc["usd_24h_change"]}
    except Exception as e:
        st.warning(f"⚠️ Market overview load issue: {e}")
    return data


def render_summary():
    data = fetch_market_data()
    indices = {
        "DOW": "^DJI",
        "S&P 500": "^GSPC",
        "NASDAQ": "^IXIC",
        "BTC/USD": "BTC-USD",
    }

    st.markdown(
        """
        <div style="text-align:center;margin-bottom:0.6rem;">
            <h3 style="color:#A7F3D0;margin-bottom:0;">📊 Market Overview</h3>
            <p style="color:#9CA3AF;margin-top:0;">Real-time global indices snapshot</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    cols = st.columns(len(indices))
    for i, (label, key) in enumerate(indices.items()):
        entry = data.get(key, {"price": None, "change": None})
        price = entry["price"]
        change = entry["change"]
        if price is None:
            with cols[i]:
                st.markdown(
                    f"<div style='background:rgba(255,255,255,0.03);border-radius:10px;"
                    f"padding:0.8rem 1rem;text-align:center;border:1px solid rgba(255,255,255,0.05);color:#9CA3AF;'>"
                    f"<b>{label}</b><br>—<br>n/a</div>",
                    unsafe_allow_html=True,
                )
        else:
            color = "lime" if change >= 0 else "tomato"
            with cols[i]:
                st.markdown(
                    f"<div style='background:rgba(255,255,255,0.03);border-radius:10px;"
                    f"padding:0.8rem 1rem;text-align:center;border:1px solid rgba(255,255,255,0.05);'>"
                    f"<b style='color:#A7F3D0;'>{label}</b><br>"
                    f"<span style='color:#E5E7EB;'>{price:,.2f}</span><br>"
                    f"<span style='color:{color};'>{change:+.2f}%</span></div>",
                    unsafe_allow_html=True,
                )

    st.markdown(
        f"<p style='text-align:center;color:#6B7280;font-size:0.8rem;margin-top:0.8rem;'>"
        f"Last updated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}</p>",
        unsafe_allow_html=True,
    )
