"""
ticker_card.py — Phase-90 Stable
Floating-glass ticker cards with hover expansion and click → chart update.
Fully defensive + compatible with Phase-90 RankingEngine and AstraPrime.
"""

import streamlit as st


# =====================================================================
# INTERNAL CARD HTML BUILDER
# =====================================================================
def _render_card_html(symbol: str, price: float, final_score: float,
                      buy_score: float, confidence: float, summary: str):
    """
    Returns clean HTML for the floating-glass ticker card.
    """

    safe_summary = (summary or "No summary available").replace('"', "'")

    return f"""
    <div class="ticker-card" title="{safe_summary}">
        <div class="ticker-header">
            <span class="ticker-symbol">{symbol}</span>
            <span class="ticker-price">${price:.2f}</span>
        </div>

        <div class="ticker-scores">
            <div>Final: {final_score:.1f}</div>
            <div>Buy: {buy_score:.1f}</div>
            <div>Conf: {confidence:.1f}</div>
        </div>

        <div class="ticker-summary">{safe_summary}</div>
    </div>

    <style>
        .ticker-card {{
            background: rgba(255,255,255,0.10);
            backdrop-filter: blur(10px);
            border-radius: 14px;
            padding: 14px;
            margin-bottom: 12px;
            border: 1px solid rgba(255,255,255,0.25);
            cursor: pointer;
            transition: 0.25s ease;
        }}
        .ticker-card:hover {{
            background: rgba(255,255,255,0.18);
            transform: translateY(-3px);
        }}
        .ticker-header {{
            display: flex;
            justify-content: space-between;
            font-size: 1.1rem;
            font-weight: 600;
            color: #F5F7FA;
        }}
        .ticker-price {{
            color: #9DA5B4;
        }}
        .ticker-scores {{
            margin-top: 6px;
            color: #C8CED6;
            font-size: 0.9rem;
            display: flex;
            justify-content: space-between;
        }}
        .ticker-summary {{
            margin-top: 6px;
            font-size: 0.85rem;
            color: #F5F7FA;
            opacity: 0;
            transition: opacity 0.25s ease;
        }}
        .ticker-card:hover .ticker-summary {{
            opacity: 1;
        }}
    </style>
    """


# =====================================================================
# PUBLIC CARD RENDERER — FINAL PHASE-90 VERSION
# =====================================================================
def render_ticker_card(
    symbol: str,
    price: float = 0.0,
    buy_score: float = 50.0,
    confidence: float = 50.0,
    summary: str = "",
    sparkline=None,
    final_score: float = 50.0,
    key: str = None,
    state_key: str = "selected_symbol",
):
    """
    Draws the ticker card.

    Returns:
        True  -> user clicked the card
        False -> not clicked
    """

    try:
        # Safe defaults
        symbol = symbol or "UNKNOWN"
        price = float(price or 0)
        buy_score = float(buy_score or 50)
        confidence = float(confidence or 50)
        final_score = float(final_score or 50)
        summary = summary or "No summary available"

    except Exception:
        symbol = "UNKNOWN"
        price = 0.0
        buy_score = 50.0
        confidence = 50.0
        final_score = 50.0
        summary = "Data error — Guardian applied."

    # -----------------------------------------------------------------
    # CLICKABLE BUTTON WRAPPER
    # -----------------------------------------------------------------
    clicked = st.button(
        label="",
        key=key or f"btn_{symbol}",
        help=summary,
        use_container_width=True,
    )

    # Render HTML card under the invisible button
    st.markdown(
        _render_card_html(
            symbol,
            price,
            final_score,
            buy_score,
            confidence,
            summary,
        ),
        unsafe_allow_html=True
    )

    # If user clicks → store symbol in session state
    if clicked:
        st.session_state[state_key] = symbol
        return True

    return False
