import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_advanced_chart(df: pd.DataFrame):
    """Render candlestick chart or fallback view safely."""
    if df.empty:
        st.warning("No price data available.")
        return

    # Case 1: Historical data (candlestick)
    if "timestamp" in df.columns and {"open", "high", "low", "close"}.issubset(
        df.columns
    ):
        show_ma = st.sidebar.checkbox("Show MA(20)", value=True)
        show_ema = st.sidebar.checkbox("Show EMA(50)", value=False)
        show_rsi = st.sidebar.checkbox("Show RSI", value=False)

        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=df["timestamp"],
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name="Price",
                    increasing_line_color="green",
                    decreasing_line_color="red",
                )
            ]
        )

        if show_ma:
            df["MA20"] = df["close"].rolling(20).mean()
            fig.add_trace(
                go.Scatter(x=df["timestamp"], y=df["MA20"],
                           mode="lines", name="MA(20)")
            )
        if show_ema:
            df["EMA50"] = df["close"].ewm(span=50, adjust=False).mean()
            fig.add_trace(
                go.Scatter(
                    x=df["timestamp"], y=df["EMA50"], mode="lines", name="EMA(50)"
                )
            )

        fig.update_layout(
            title="Advanced Candlestick Chart", xaxis_rangeslider_visible=False
        )
        st.plotly_chart(fig, use_container_width=True)

        if show_rsi:
            st.line_chart(df["close"].diff().fillna(
                0).rolling(14).mean(), height=100)

    # Case 2: Live-only data (no timestamp)
    elif "price" in df.columns and "symbol" in df.columns:
        st.subheader("📈 Live Prices")
        for _, row in df.iterrows():
            st.metric(
                label=row["symbol"],
                value=f"${row['price']}",
                delta=row.get("change_pct", "—"),
            )
    else:
        st.warning("Unrecognized data format for chart rendering.")
