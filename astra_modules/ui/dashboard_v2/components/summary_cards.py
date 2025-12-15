import streamlit as st

def render_summary_cards(data: dict):
    cols = st.columns(4)
    metrics = {
        "Confidence": data.get("confidence", "—"),
        "Signal": data.get("signal", "—"),
        "Risk": data.get("risk_level", "—"),
        "Status": data.get("status", "—"),
    }
    for col, (label, value) in zip(cols, metrics.items()):
        col.metric(label, value)
