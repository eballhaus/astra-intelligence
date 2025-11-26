"""
render_advanced_chart.py — Phase-90
Advanced defensive Plotly chart renderer for Astra
Handles malformed data, empty data, and layout polish
"""

import pandas as pd
import plotly.graph_objects as go


# =====================================================================
# SAFETY CHECKS
# =====================================================================
def _safe(df, cols):
    """Ensures DataFrame has required columns."""
    if df is None:
        return False
    if df.empty:
        return False
    return set(cols).issubset(df.columns)


# =====================================================================
# MAIN CHART FUNCTION
# =====================================================================
def render_advanced_chart(symbol: str, df: pd.DataFrame):
    """
    Renders a beautiful Phase-90 candlestick + line chart.
    
    Returns:
        str (HTML fragment)
    """

    required = {"date", "open", "high", "low", "close"}

    # ----------------------------------------------------------
    # FALLBACK FOR BAD DATA
    # ----------------------------------------------------------
    if not _safe(df, required):
        return f"""
        <div style='padding:12px; color:#DDD; font-size:14px;'>
            No valid price data available for <b>{symbol}</b>.
        </div>
        """

    # ----------------------------------------------------------
    # CLEAN / FIX DATE FORMAT
    # ----------------------------------------------------------
    try:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])
    except Exception:
        return f"""
        <div style='padding:12px; color:#DDD; font-size:14px;'>
            Chart error: Unable to parse date data for <b>{symbol}</b>.
        </div>
        """

    # ----------------------------------------------------------
    # CREATE CHART
    # ----------------------------------------------------------
    fig = go.Figure()

    # Candlestick Layer
    fig.add_trace(go.Candlestick(
        x=df["date"],
        open=df["open"],
        high=df["high"],
        low=df["low"],
        close=df["close"],
        name=f"{symbol} Price",
        increasing_line_color="#00FFAA",
        decreasing_line_color="#FF5A5A",
        increasing_fillcolor="rgba(0,255,170,0.35)",
        decreasing_fillcolor="rgba(255,90,90,0.35)",
        hovertemplate=(
            "<b>%{x}</b><br><br>"
            "Open: $%{open:.2f}<br>"
            "High: $%{high:.2f}<br>"
            "Low: $%{low:.2f}<br>"
            "Close: $%{close:.2f}<extra></extra>"
        )
    ))

    # Close Price Line
    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["close"],
        mode="lines",
        line=dict(color="#00A3FF", width=2),
        name="Close",
        hovertemplate="Close: $%{y:.2f}<extra></extra>"
    ))

    # ----------------------------------------------------------
    # LAYOUT
    # ----------------------------------------------------------
    fig.update_layout(
        title=f"{symbol} Price Chart",
        template="plotly_dark",
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=20, r=20, t=40, b=20),
        xaxis_title="Date",
        yaxis_title="Price ($)",
        xaxis=dict(
            showgrid=True,
            gridcolor="#222222",
            rangeslider_visible=False
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="#222222"
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            orientation="h",
            x=0,
            y=1.15,
            font=dict(size=12)
        )
    )

    # ----------------------------------------------------------
    # RETURN HTML (EMBEDDABLE IN STREAMLIT)
    # ----------------------------------------------------------
    return fig.to_html(
        include_plotlyjs="cdn",
        full_html=False,
        config={
            "responsive": True,
            "displayModeBar": True,
            "scrollZoom": False
        }
    )
