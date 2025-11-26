import streamlit as st

def render_placeholder_card(data):
    """
    Temporary card for SET 1.
    Not styled yet — will be replaced in SET 3.
    """
    st.markdown("---")
    st.write(f"**{data.get('symbol', 'UNKNOWN')}** — Composite Score: {round(data.get('composite_score', 0), 2)}")
    st.write(f"BuyScore: {data.get('buy_score', 'N/A')}")
    st.write(f"SafetyScore: {data.get('safety_score', 'N/A')}")
    st.write(f"TrendStrength: {data.get('trend_strength', 'N/A')}")
