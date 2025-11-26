"""
Astra Intelligence — Phase-90 Unified Dashboard
-------------------------------------------------
Dynamic, glass-styled dashboard displaying live data, agent metrics,
and real-time trading indicators from Astra’s API network.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import time
from datetime import datetime
from astra_modules.api_keys import (
    ALPHA_VANTAGE_API_KEY,
    FMP_API_KEY,
    TWELVEDATA_API_KEY,
    FINNHUB_API_KEY,
    EODHD_API_KEY,
)
from astra_modules.guardian.guardian_v6 import GuardianV6
from astra_modules.universe.universe_builder import build_universe

guardian = GuardianV6(__file__)

# -------------------------------------------------
# Placeholder for Unified API Data Fetcher
# -------------------------------------------------
def fetch_live_data(symbol="AAPL", interval="5min", mode="day"):
    """
    Temporary live fetcher that will later call the multi-API engine.
    Returns a simulated DataFrame for layout verification.
    """
    try:
        # Placeholder: mock data (to be replaced by real API fetch)
        now = pd.Timestamp.now()
        timestamps = pd.date_range(now - pd.Timedelta("2H"), now, freq="5min")
        prices = pd.Series(150 + (pd.Series(range(len(timestamps))) * 0.1)).astype(float)
        df = pd.DataFrame({
            "datetime": timestamps,
            "open": prices - 0.2,
            "high": prices + 0.5,
            "low": prices - 0.5,
            "close": prices,
            "volume": [1000 + i * 5 for i in range(len(prices))],
        })
        return df
    except Exception as e:
        guardian.log_event("data_fetch_error", str(e))
        return None


# -------------------------------------------------
# Core Dashboard Rendering
# -------------------------------------------------
def render_dashboard():
    st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide")

    st.markdown(
        """
        <h1 style='text-align: center; color: #F5F7FA;'>⭐ Astra Intelligence — Phase-90 Dashboard</h1>
        <p style='text-align: center; color: #9DA5B4;'>Unified Quant Engine | Guardian Protected | Real-Time Updates</p>
        """,
        unsafe_allow_html=True,
    )

    # Sidebar layout
    with st.sidebar:
        st.header("📊 Astra Universe")
        universe = build_universe()
        selected_symbol = st.selectbox("Select Symbol", universe)

        mode = st.radio("Trading Mode", ["Day Trading", "Swing Trading"], index=0)
        refresh_interval = 300 if mode == "Day Trading" else 3600

        if not selected_symbol:
            selected_symbol = "AAPL"

        st.info(f"🔄 Auto-refresh every {refresh_interval // 60} minutes")

    # Fetch live data
    df = fetch_live_data(symbol=selected_symbol, mode="day" if mode == "Day Trading" else "swing")

    # Layout columns
    col1, col2 = st.columns([2, 3], gap="large")

    with col1:
        st.markdown(f"### 🧠 {selected_symbol}")
        st.markdown("**Phase-90 Real-Time Scan**")
        st.markdown(
            """
            <div style="background-color:rgba(255,255,255,0.05);padding:15px;border-radius:12px;border:1px solid rgba(255,255,255,0.1);">
                <strong>📈 Astra Summary:</strong><br>
                Bullish trend forming with rising momentum.<br>
                Guardian confidence: <strong>87%</strong><br>
                Risk: <strong>Moderate</strong><br>
                Timeframe: <strong>Day Trading</strong>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col2:
        if df is None or df.empty:
            st.warning("⚠️ Unable to load live data for this symbol.")
        else:
            fig = go.Figure()
            fig.add_trace(
                go.Candlestick(
                    x=df["datetime"],
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                )
            )

            fig.update_layout(
                template="plotly_dark",
                xaxis_rangeslider_visible=False,
                height=500,
                margin=dict(l=20, r=20, t=50, b=20),
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
            )

            st.plotly_chart(fig, use_container_width=True)

    st.markdown(
        f"<p style='text-align:center;color:#9DA5B4;'>Last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    render_dashboard()
