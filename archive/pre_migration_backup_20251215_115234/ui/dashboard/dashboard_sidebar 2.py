import streamlit as st
from ui.dashboard.theme_loader import apply_theme

def render_sidebar():
    with st.sidebar:
        st.header("⚙️ Dashboard Controls")
        symbol = st.text_input("Symbol", value="SPX")
        theme_choice = st.selectbox("Theme", ["AstraGlass", "Light", "Dark"])
        apply_theme(theme_choice)
        st.divider()
        return symbol
