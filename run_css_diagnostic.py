import streamlit as st
import pathlib

st.set_page_config(page_title="Astra CSS Diagnostic", layout="wide")
st.title("🧠 Astra CSS Diagnostic")

st.write(
    """
This test will list every CSS file Streamlit is currently loading.
If something is setting the background to black, you'll see it here.
"""
)

css_dir = pathlib.Path(__file__).parent / "astra_modules" / "ui" / "dashboard"
for css_file in css_dir.glob("*.css"):
    st.markdown(f"### {css_file.name}")
    st.code(css_file.read_text(encoding="utf-8")[:400])

st.markdown("---")
st.markdown("**End of local CSS files**")

st.write(
    """
⬆️ Scroll through and look for lines such as  
`background-color: #000;` or `color-scheme: dark;`
"""
)

st.write(
    "If you don't see those, the black background is coming from Streamlit's internal CSS."
)
