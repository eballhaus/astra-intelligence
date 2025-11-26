# ===============================================================
# Astra Intelligence 7.0 — Plotly Theme
# Frosted-Glass Dark Mode + Pastel Grid
# Completely rebuilt for modern UI and readability
# ===============================================================

import plotly.graph_objects as go


def apply_plotly_theme(fig: go.Figure):
    """
    Applies Astra's global dark frosted-glass style theme.
    This theme is used for ALL charts (price, RSI, MACD, volume).
    """

    fig.update_layout(

        # -------------------------------------------------------
        # Background: Dark Matte + Light Transparency
        # -------------------------------------------------------
        paper_bgcolor="rgba(18,18,18,0.25)",   # frosted glass panel
        plot_bgcolor="rgba(0,0,0,0.0)",        # fully transparent plot area

        # -------------------------------------------------------
        # Fonts
        # -------------------------------------------------------
        font=dict(
            family="Arial, sans-serif",
            size=12,
            color="#E8E8E8"  # soft light gray
        ),

        # -------------------------------------------------------
        # Margins
        # -------------------------------------------------------
        margin=dict(t=35, b=25, l=55, r=25),

        # -------------------------------------------------------
        # Legend Style
        # -------------------------------------------------------
        legend=dict(
            bgcolor="rgba(0,0,0,0.3)",
            bordercolor="rgba(255,255,255,0.08)",
            borderwidth=1,
            font=dict(color="#D8D8D8"),
            orientation="h",
            yanchor="bottom",
            y=1.02,
            x=0.01,
        ),

        # -------------------------------------------------------
        # Axes Styling
        # -------------------------------------------------------
        xaxis=dict(
            showgrid=True,
            gridcolor="rgba(200,200,200,0.10)",  # soft pastel grid
            gridwidth=0.4,
            zeroline=False,
            showline=True,
            linecolor="rgba(255,255,255,0.20)",
            tickfont=dict(color="#CFCFCF"),
        ),
        yaxis=dict(
            showgrid=True,
            gridcolor="rgba(200,200,200,0.10)",
            gridwidth=0.4,
            zeroline=False,
            showline=True,
            linecolor="rgba(255,255,255,0.20)",
            tickfont=dict(color="#CFCFCF"),
        ),

        # -------------------------------------------------------
        # Improve interaction feel
        # -------------------------------------------------------
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(40,40,40,0.85)",
            font_size=12,
            font_color="#EAEAEA",
        ),

        transition_duration=0,
    )

    # -----------------------------------------------------------
    # Candlestick improvements
    # -----------------------------------------------------------
    fig.update_traces(selector=dict(type="candlestick"),
                      increasing_fillcolor="#1EB5A4",
                      increasing_line_color="#1EB5A4",
                      decreasing_fillcolor="#D45A6A",
                      decreasing_line_color="#D45A6A",
                      )

    return fig
