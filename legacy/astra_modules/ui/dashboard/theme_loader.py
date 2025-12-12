# astra_modules/ui/dashboard/theme_loader.py

"""
AstraGlass Theme Loader — NeuralGlass Interface v3.0
Handles global CSS injection for Astra Intelligence dashboards.
Compatible with both `load_theme()` and legacy `apply_theme()`.
"""

from pathlib import Path

import streamlit as st


def load_theme():
    """
    Load and inject the AstraGlass theme CSS file into the Streamlit app.
    This function should be called *after* st.set_page_config() but before
    rendering any major UI components.
    """
    try:
        css_path = Path(__file__).parent / "astra_theme.css"

        if not css_path.exists():
            st.warning(
                "⚠️ Astra theme file not found: astra_theme.css missing.")
            return

        with open(css_path, "r", encoding="utf-8") as css_file:
            css_content = css_file.read()

        # Inject the CSS into Streamlit
        st.markdown(f"<style>{css_content}</style>", unsafe_allow_html=True)

    except Exception as e:
        st.error(f"🚨 Failed to load Astra theme: {e}")


# ---------------------------------------------------------------------
# ✅ Backward compatibility for older modules using apply_theme()
# ---------------------------------------------------------------------
def apply_theme():
    """
    Legacy alias for load_theme() to maintain backward compatibility.
    Use load_theme() moving forward.
    """
    load_theme()
