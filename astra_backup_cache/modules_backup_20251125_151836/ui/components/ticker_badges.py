"""
Ticker Badges Component (Phase-45)
----------------------------------
Simple pill-style badges used to display selected tickers.
"""

import streamlit as st

def render_ticker_badges(symbols):
    """
    Render tickers as pill-style badges on one horizontal row.
    """

    if not symbols:
        return

    cols = st.columns(len(symbols))

    for i, sym in enumerate(symbols):
        with cols[i]:
            st.markdown(
                f"""
                <div style="
                    background-color:#111827;
                    color:white;
                    padding:6px 14px;
                    border-radius:12px;
                    margin:4px 0;
                    display:inline-block;
                    text-align:center;
                    font-size:14px;
                    font-weight:600;
                    border:1px solid #4b5563;
                ">
                    {sym}
                </div>
                """,
                unsafe_allow_html=True
            )
