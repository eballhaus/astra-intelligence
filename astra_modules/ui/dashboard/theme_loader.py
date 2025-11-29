from pathlib import Path

import streamlit as st


def apply_theme():
    """Load AstraGlass theme once."""
    css_path = Path(__file__).parent / "astra_theme.css"

    # Force Streamlit to behave as 'light' base
    st.markdown(
        "<style>:root { color-scheme: light !important; }</style>",
        unsafe_allow_html=True,
    )

    if css_path.exists():
        with open(css_path, encoding="utf-8") as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

    # Explicit gradient override so nothing can blank it out
    st.markdown(
        """
        <style>
        html, body, .stApp {
            background: radial-gradient(circle at 25% 25%, rgba(17,24,39,0.95), rgba(3,7,18,0.98)) !important;
            color: #E5E7EB !important;
            font-family: 'Inter', sans-serif !important;
        }
        </style>
    """,
        unsafe_allow_html=True,
    )
