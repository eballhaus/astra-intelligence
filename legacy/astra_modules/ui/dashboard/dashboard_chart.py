"""
Astra Intelligence — Advanced Candle Chart v4.2
------------------------------------------------
Candlestick + MA10/30 + Bollinger Bands + RSI + MACD + Momentum + Trend Overlay
Now includes AI buy/sell signal markers, Guardian watermark, and AstraGlass styling.
Includes automatic date-column normalization and error recovery.
"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_chart(df: pd.DataFrame, symbol: str = ""):
    """
    Render Astra's advanced financial chart with indicators and AI markers.
    """

    # ──────────────────────────────────────────
    # Validate Data
    # ──────────────────────────────────────────
    if (
        df is None
        or isinstance(df, dict)
        or not hasattr(df, "empty")
        or df.empty
        or "close" not in getattr(df, "columns", [])
    ):
        st.warning("⚠️ No valid chart data available.")
        return None

    try:
        df = df.copy()

        # ──────────────────────────────────────────
        # Normalize date/time columns (prevents 'date' key errors)
        # ──────────────────────────────────────────
        possible_date_cols = ["date", "timestamp", "Datetime", "time", "Date"]
        found_date_col = next(
            (c for c in possible_date_cols if c in df.columns), None)

        if not found_date_col:
            st.warning("⚠️ No date or timestamp column found in data.")
            df["date"] = pd.RangeIndex(
                start=0, stop=len(df)
            )  # fallback sequential index
        elif found_date_col != "date":
            df["date"] = pd.to_datetime(df[found_date_col])

        # ──────────────────────────────────────────
        # Indicators
        # ──────────────────────────────────────────
        df["ma_fast"] = df["close"].ewm(span=10).mean()
        df["ma_slow"] = df["close"].ewm(span=30).mean()
        df["ma20"] = df["close"].rolling(20).mean()
        df["upper"] = df["ma20"] + 2 * df["close"].rolling(20).std()
        df["lower"] = df["ma20"] - 2 * df["close"].rolling(20).std()

        delta = df["close"].diff()
        gain = delta.clip(lower=0).rolling(14).mean()
        loss = -delta.clip(upper=0).rolling(14).mean()
        rs = gain / (loss + 1e-9)
        df["rsi"] = 100 - (100 / (1 + rs))

        ema12 = df["close"].ewm(span=12).mean()
        ema26 = df["close"].ewm(span=26).mean()
        df["macd"] = ema12 - ema26
        df["macd_signal"] = df["macd"].ewm(span=9).mean()

        df["momentum"] = df["close"] - df["close"].shift(4)
        df["momentum_smooth"] = df["momentum"].rolling(8).mean()

        # ──────────────────────────────────────────
        # Simple AI Signal Logic
        # ──────────────────────────────────────────
        df["buy_signal"] = (df["macd"] > df["macd_signal"]) & (
            df["momentum_smooth"] > 0
        )
        df["sell_signal"] = (df["macd"] < df["macd_signal"]) & (
            df["momentum_smooth"] < 0
        )

        # ──────────────────────────────────────────
        # Build Plotly Figure
        # ──────────────────────────────────────────
        fig = go.Figure()

        # Candles
        fig.add_trace(
            go.Candlestick(
                x=df["date"],
                open=df["open"],
                high=df["high"],
                low=df["low"],
                close=df["close"],
                name="Candles",
                increasing_line_color="#16A34A",
                decreasing_line_color="#DC2626",
            )
        )

        # MAs and Bands
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["ma_fast"],
                mode="lines",
                name="MA10",
                line=dict(width=1.2, color="rgba(255,255,255,0.6)"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["ma_slow"],
                mode="lines",
                name="MA30",
                line=dict(width=1.2, dash="dot",
                          color="rgba(255,255,255,0.3)"),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["upper"],
                mode="lines",
                name="BB Upper",
                line=dict(color="rgba(255,255,255,0.25)", width=0.8),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["lower"],
                mode="lines",
                name="BB Lower",
                line=dict(color="rgba(255,255,255,0.25)", width=0.8),
                fill="tonexty",
                fillcolor="rgba(255,255,255,0.05)",
            )
        )

        # Momentum
        fig.add_trace(
            go.Bar(
                x=df["date"],
                y=df["momentum"],
                name="Momentum",
                marker_color="rgba(173,216,230,0.25)",
                yaxis="y2",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["momentum_smooth"],
                name="Momentum Trend",
                line=dict(color="#14B8A6", width=1.8),
                yaxis="y2",
            )
        )

        # RSI + MACD
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["rsi"],
                name="RSI (14)",
                line=dict(color="orange", width=1),
                yaxis="y3",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["macd"],
                name="MACD",
                line=dict(color="cyan", width=1.5),
                yaxis="y4",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["date"],
                y=df["macd_signal"],
                name="Signal",
                line=dict(color="magenta", width=1, dash="dot"),
                yaxis="y4",
            )
        )

        # ──────────────────────────────────────────
        # AI Buy/Sell Markers
        # ──────────────────────────────────────────
        buys = df[df["buy_signal"]]
        sells = df[df["sell_signal"]]

        fig.add_trace(
            go.Scatter(
                x=buys["date"],
                y=buys["close"],
                mode="markers",
                name="Buy Signal",
                marker=dict(
                    symbol="triangle-up",
                    size=10,
                    color="#22C55E",
                    line=dict(color="white", width=0.5),
                ),
                hovertemplate="Buy: %{y:.2f}<extra></extra>",
            )
        )

        fig.add_trace(
            go.Scatter(
                x=sells["date"],
                y=sells["close"],
                mode="markers",
                name="Sell Signal",
                marker=dict(
                    symbol="triangle-down",
                    size=10,
                    color="#EF4444",
                    line=dict(color="white", width=0.5),
                ),
                hovertemplate="Sell: %{y:.2f}<extra></extra>",
            )
        )

        # ──────────────────────────────────────────
        # Layout & Theme
        # ──────────────────────────────────────────
        fig.update_layout(
            height=700,
            paper_bgcolor="rgba(10,12,15,0.0)",
            plot_bgcolor="rgba(10,12,15,0.0)",
            margin=dict(l=40, r=20, t=60, b=40),
            font=dict(family="Inter, sans-serif", color="#E5E7EB"),
            xaxis=dict(showgrid=False, color="#9CA3AF"),
            yaxis=dict(
                title="Price", color="#E5E7EB", gridcolor="rgba(255,255,255,0.05)"
            ),
            yaxis2=dict(overlaying="y", side="right",
                        showgrid=False, color="#14B8A6"),
            yaxis3=dict(
                title="RSI",
                overlaying="y",
                side="left",
                position=0.02,
                range=[0, 100],
                color="orange",
            ),
            yaxis4=dict(
                title="MACD", overlaying="y", side="right", position=0.98, color="cyan"
            ),
            legend=dict(
                orientation="h",
                y=1.02,
                x=0.5,
                xanchor="center",
                font=dict(color="#E5E7EB"),
            ),
            title=dict(
                text=f"📈 {symbol} — Advanced Chart",
                x=0.5,
                font=dict(color="#A7F3D0", size=16),
            ),
        )

        fig.add_annotation(
            text="🛡️ Guardian-Verified",
            xref="paper",
            yref="paper",
            x=1.0,
            y=1.12,
            showarrow=False,
            font=dict(size=10, color="#14B8A6"),
            align="right",
        )

        fig.update_xaxes(
            rangeslider_visible=True,
            rangeselector=dict(
                buttons=[
                    dict(count=7, label="1W", step="day", stepmode="backward"),
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=3, label="3M", step="month", stepmode="backward"),
                    dict(step="all", label="All"),
                ]
            ),
        )

        st.plotly_chart(fig, use_container_width=True,
                        config={"displayModeBar": False})
        return fig

    except Exception as e:
        st.error(f"🚨 Chart rendering error: {e}")
        return None
