import streamlit as st
from core.guardian.guardian_v7 import guardian_log
from engine.data_orchestrator import fetch_live_data
from engine.data_funnel import select_top_assets
from forecast.astra_prime import get_predictions  # hypothetical prediction module

st.set_page_config(layout="wide")


def render_insight_board():
    st.title("🧠 Astra Insight Board")

    # Split columns: stocks / cryptos
    col_stocks, col_crypto = st.columns(2)
    top_assets = select_top_assets(mode="live", limit=12)
    stocks = top_assets[top_assets["symbol"].str.isalpha()].head(6)
    cryptos = top_assets[top_assets["symbol"].str.contains("USD")].head(6)

    with col_stocks:
        st.subheader("📈 Top 6 Stocks")
        for _, row in stocks.iterrows():
            render_asset_card(row)

    with col_crypto:
        st.subheader("💎 Top 6 Cryptos")
        for _, row in cryptos.iterrows():
            render_asset_card(row)

    # Chart container
    st.markdown("---")
    st.subheader("📊 Advanced Chart")
    render_advanced_chart()


def render_asset_card(row):
    import random

    symbol = row["symbol"]
    pred = (
        get_predictions(symbol)
        if "get_predictions" in globals()
        else {
            "price": round(random.uniform(0.5, 3.0), 2),
            "percent": round(random.uniform(-5, 12), 2),
            "timeframe": "7 d",
            "stop_loss": round(random.uniform(-3, -8), 2),
            "confidence": round(random.uniform(70, 97), 1),
            "grade": random.choice(["A+", "A", "B+", "B"]),
            "reason": "Strong momentum and volume trend.",
        }
    )

    with st.container():
        st.markdown(f"#### {symbol}")
        st.write(
            f"**Prediction:** ${pred['price']}  ({pred['percent']}%) in {pred['timeframe']}"
        )
        st.write(f"**Stop-loss:** {pred['stop_loss']}%")
        st.write(f"**Confidence:** {pred['confidence']}%")
        st.write(f"**Buy grade:** {pred['grade']}")
        st.caption(pred["reason"])
        if st.button(f"Show Chart → {symbol}", key=f"btn_{symbol}"):
            st.session_state["selected_symbol"] = symbol
            guardian_log.info(f"[UI] Chart selected → {symbol}")


def render_advanced_chart():
    import plotly.graph_objects as go

    symbol = st.session_state.get("selected_symbol", "AAPL")
    df = fetch_live_data(symbol)
    if df.empty:
        st.warning(f"No data for {symbol}")
        return

    fig = go.Figure()

    # Candlesticks
    fig.add_trace(
        go.Candlestick(
            x=df["t"],
            open=df["o"],
            high=df["h"],
            low=df["l"],
            close=df["c"],
            name="Price",
            increasing_line_color="green",
            decreasing_line_color="red",
        )
    )

    # Momentum line (close-to-close % change)
    df["momentum"] = df["c"].pct_change() * 100
    fig.add_trace(
        go.Scatter(
            x=df["t"],
            y=df["momentum"],
            mode="lines",
            name="Momentum",
            line=dict(color="blue"),
        )
    )

    # Optional indicator toggles
    indicators = st.multiselect(
        "Show Indicators",
        ["EMA 20", "EMA 50", "RSI 14", "Bollinger Bands"],
        default=["EMA 20"],
    )
    if "EMA 20" in indicators:
        df["ema20"] = df["c"].ewm(span=20).mean()
        fig.add_trace(
            go.Scatter(
                x=df["t"], y=df["ema20"], name="EMA 20", line=dict(color="orange")
            )
        )
    if "EMA 50" in indicators:
        df["ema50"] = df["c"].ewm(span=50).mean()
        fig.add_trace(
            go.Scatter(
                x=df["t"], y=df["ema50"], name="EMA 50", line=dict(color="purple")
            )
        )
    # RSI & Bollinger Bands could be added similarly

    fig.update_layout(
        height=600, xaxis_rangeslider_visible=False, template="plotly_dark"
    )
    st.plotly_chart(fig, width="stretch")
