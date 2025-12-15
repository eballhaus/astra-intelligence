import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_chart(data):
    st.markdown("### 📈 Performance Chart")
    try:
        df = pd.DataFrame(data["history"])
    except Exception:
        st.warning("⚠️ Invalid chart data format.")
        return
    fig = go.Figure(
        data=[
            go.Candlestick(
                x=pd.to_datetime(df.get("time", range(len(df)))),
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                increasing_line_color="green",
                decreasing_line_color="red",
                name="Price",
            )
        ]
    )
    df["MA5"] = df["close"].rolling(5).mean()
    fig.add_trace(
        go.Scatter(
            x=pd.to_datetime(df.get("time", range(len(df)))),
            y=df["MA5"],
            line=dict(color="blue", width=1.2),
            name="5-MA",
        )
    )
    fig.update_layout(
        height=420,
        template="plotly_white",
        width="stretch",
        xaxis_rangeslider_visible=False,
    )
    st.plotly_chart(fig, use_container_width=False)
