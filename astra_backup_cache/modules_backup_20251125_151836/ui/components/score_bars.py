import streamlit as st

# ============================================================
# SCORE BAR RENDERERS — Buy / Safety / Volatility
# ============================================================

def render_buy_bar(score: float):
    pct = min(max(float(score), 0), 100)
    st.markdown(
        f"<div class='astra-score-bar astra-buy-bar' style='width:{pct}%;'></div>",
        unsafe_allow_html=True
    )

def render_safety_bar(score: float):
    pct = min(max(float(score), 0), 100)
    st.markdown(
        f"<div class='astra-score-bar astra-safety-bar' style='width:{pct}%;'></div>",
        unsafe_allow_html=True
    )

def render_volatility_bar(vol: float):
    pct = min(max(float(vol), 0), 100)
    st.markdown(
        f"<div class='astra-score-bar astra-volatility-bar' style='width:{pct}%;'></div>",
        unsafe_allow_html=True
    )
