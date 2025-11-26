import streamlit as st

# ============================================================
# HOVER SUMMARY — Placeholder For Interactive JS Popup (Phase 47)
# ============================================================

def render_hover_summary(data: dict):
    """
    Future interactive summary (currently static).
    """

    st.markdown(
        f"""
        <div class='astra-hover-box'>
            <strong>Trend:</strong> {data.get("trend_label","N/A")}<br>
            <strong>Volume:</strong> {data.get("volume_profile","N/A")}<br>
            <strong>Pattern:</strong> {data.get("pattern","None")}<br>
            <strong>Forecast:</strong> {data.get("forecast_direction","N/A")}<br>
            <strong>Strength:</strong> {data.get("strength_score","N/A")}<br>
        </div>
        """,
        unsafe_allow_html=True
    )
