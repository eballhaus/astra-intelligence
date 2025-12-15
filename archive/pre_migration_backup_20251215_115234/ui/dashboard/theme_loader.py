import streamlit as st
from pathlib import Path

def apply_theme(theme="AstraGlass"):
    css_path = Path(__file__).resolve().parent / "astra_theme.css"
    try:
        st.markdown(f"<style>{css_path.read_text()}</style>", unsafe_allow_html=True)
    except Exception as e:
        st.warning(f"Theme load failed: {e}")
