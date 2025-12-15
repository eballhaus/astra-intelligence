import streamlit as st

def render_summary(data=None):
    st.markdown("### 🧩 System Summary")
    if data is None:
        st.info("No summary data.")
        return
    cols = st.columns(3)
    cols[0].metric("Trend", data.get("trend", "Neutral"))
    cols[1].metric("Volatility", data.get("volatility", "N/A"))
    cols[2].metric("AI Confidence", f"{data.get('confidence', 0)} %")
