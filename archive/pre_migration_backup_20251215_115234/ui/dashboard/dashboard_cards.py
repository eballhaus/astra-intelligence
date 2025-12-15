import streamlit as st

def render_symbol_card(data=None):
    st.markdown("### 📊 Symbol Overview")
    if data is None:
        st.info("No live data available.")
        return
    col1, col2, col3 = st.columns(3)
    col1.metric("Symbol", data.get("symbol", "N/A"))
    col2.metric("Price", f"{data.get('price', 0):,.2f}")
    col3.metric("Change (%)", f"{data.get('change_pct', 0):+.2f}%")
    st.metric("Trend", data.get("trend", "Neutral"))
    st.metric("Volatility", data.get("volatility", "N/A"))
