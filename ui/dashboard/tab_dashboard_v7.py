import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timezone
from engine.data_orchestrator import fetch_live_data
import time

# ======================================================
# Astra Intelligence — Streamlit Dashboard v9.0a (Restored Live Version)
# ======================================================

def render_dashboard():
    st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide")

    # ======================================================
    # 📊 MARKET OVERVIEW
    # ======================================================
    st.markdown("### 📊 Market Overview")
    cols = st.columns(4)
    market_data = [
        {"name": "S&P 500", "value": "4,862 (+0.43%)"},
        {"name": "NASDAQ", "value": "15,102 (+0.56%)"},
        {"name": "DOW JONES", "value": "38,210 (+0.31%)"},
        {"name": "Bitcoin", "value": "$67,340 (+1.2%)"},
    ]
    for i, m in enumerate(market_data):
        with cols[i]:
            st.metric(label=m["name"], value=m["value"])

    st.divider()

    # ======================================================
    # ⚡ LIVE ASTRA SIGNALS
    # ======================================================
    st.markdown("### ⚡ Live Astra Signals")

    # --- Live Astra Feed ---
    try:
        live_data = fetch_live_data()
        if not isinstance(live_data, list):
            st.warning("Live data feed returned unexpected format. Using fallback...")
            live_data = []
    except Exception as e:
        st.error(f"Live data fetch failed: {e}")
        live_data = []

    stocks = [d for d in live_data if d.get("type", "stock") == "stock"][:6]
    cryptos = [d for d in live_data if d.get("type", "crypto") == "crypto"][:6]

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📈 Stocks")
        if not stocks:
            st.info("No live stock data available.")
        for s in stocks:
            with st.container(border=True):
                st.markdown(f"**{s['symbol']}** — Live: ${s.get('price', '--')}")
                st.write(f"Prediction: ${s.get('target','--')} ({s.get('pred_pct','--')}%) | {s.get('term','Swing')}")
                st.write(f"Stop-Loss: ${s.get('stop','--')} ({s.get('stop_pct','--')}%)")
                st.write(f"Confidence: {s.get('confidence','--')}% | Grade: {s.get('grade','--')}")
                st.caption(f"Reason: {s.get('reason','Astra signal pending…')}")

    with col2:
        st.subheader("🪙 Cryptos")
        if not cryptos:
            st.info("No live crypto data available.")
        for c in cryptos:
            with st.container(border=True):
                st.markdown(f"**{c['symbol']}** — Live: ${c.get('price', '--')}")
                st.write(f"Prediction: ${c.get('target','--')} ({c.get('pred_pct','--')}%) | {c.get('term','Day')}")
                st.write(f"Stop-Loss: ${c.get('stop','--')} ({c.get('stop_pct','--')}%)")
                st.write(f"Confidence: {c.get('confidence','--')}% | Grade: {c.get('grade','--')}")
                st.caption(f"Reason: {c.get('reason','Astra signal pending…')}")

    st.divider()

    # ======================================================
    # 📈 ADVANCED CHART — Candlestick + Indicators
    # ======================================================
    st.markdown("### 📈 Advanced Live Chart")

    df = pd.DataFrame({
        "time": pd.date_range(start="2025-12-20", periods=50, freq="H"),
        "open": pd.Series(range(100, 150)),
        "high": pd.Series(range(105, 155)),
        "low": pd.Series(range(95, 145)),
        "close": pd.Series(range(102, 152)),
        "momentum": pd.Series(range(50, 100)),
        "ema_short": pd.Series(range(101, 151)),
        "ema_long": pd.Series(range(99, 149)),
    })

    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=df["time"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        increasing_line_color="green", decreasing_line_color="red", name="Price"))
    fig.add_trace(go.Scatter(x=df["time"], y=df["momentum"], mode="lines", name="Momentum", line=dict(color="orange", width=2)))
    fig.add_trace(go.Scatter(x=df["time"], y=df["ema_short"], mode="lines", name="EMA Short", line=dict(color="cyan", width=1)))
    fig.add_trace(go.Scatter(x=df["time"], y=df["ema_long"], mode="lines", name="EMA Long", line=dict(color="blue", width=1)))

    fig.update_layout(
        title="Astra Advanced Chart",
        template="plotly_dark",
        xaxis_title="Time",
        yaxis_title="Price",
        legend=dict(orientation="h", yanchor="bottom", y=-0.3, xanchor="center", x=0.5)
    )
    st.plotly_chart(fig, use_container_width=True)

    # ======================================================
    # 🕒 Footer
    # ======================================================
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    st.caption(f"Last updated: {now}")

    time.sleep(15)
    try:
        st.rerun()
    except AttributeError:
        st.experimental_rerun()


if __name__ == "__main__":
    render_dashboard()
