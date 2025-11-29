import streamlit as st
from astra_modules.ui.dashboard.tab_dashboard import render_dashboard

st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide")

# --- Final override to defeat Streamlit's dark layer ---
st.markdown("""
<style>
:root { color-scheme: light !important; }
html, body, .stApp, [data-testid="stAppViewContainer"] {
    background: radial-gradient(circle at 25% 25%, rgba(17,24,39,0.95), rgba(3,7,18,0.98)) !important;
    color: #E5E7EB !important;
    font-family: 'Inter', sans-serif !important;
}
[data-testid="stDecoration"],
[data-testid="stHeader"],
[data-testid="stStatusWidget"] {
    background: transparent !important;
}
</style>
""", unsafe_allow_html=True)
# --------------------------------------------------------

render_dashboard()

