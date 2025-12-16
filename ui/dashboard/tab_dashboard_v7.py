
import streamlit as st
from engine.data_orchestrator import fetch_live_data
from astra_modules.engine.data_hydra import hydra_sentiment_global

def tab_dashboard_live(symbol="AAPL"):
    """Hydra Live Dashboard — fetch and visualize live data."""
    st.header(f"📊 Live Hydra Dashboard – {symbol}")

    with st.spinner("Fetching live data..."):
        df = fetch_live_data(symbol)
        sentiment = hydra_sentiment_global(symbol)
    
    if df.empty:
        st.warning(f"No live data found for {symbol} — using fallback.")
    else:
        st.success(f"✅ Live data fetched for {symbol}")

    # Live metric cards
    try:
        price = df['c'].iloc[-1]
        open_ = df['o'].iloc[-1]
        delta = price - open_
        st.metric(label="Last Price", value=f"${price:.2f}", delta=f"{delta:+.2f}")
        st.caption(f"Hydra Sentiment: {sentiment:.2f}")
    except Exception:
        st.info("Live cards unavailable — data incomplete.")

    # Render live chart
    try:
        import plotly.graph_objects as go
        fig = go.Figure(data=[go.Candlestick(
            x=df['t'],
            open=df['o'],
            high=df['h'],
            low=df['l'],
            close=df['c']
        )])
        st.plotly_chart(fig, use_container_width=True)
    except Exception as e:
        st.error(f"Chart render failed: {e}")

