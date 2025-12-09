import streamlit as st

from astra_core.ui import dashboard

st.set_page_config(page_title="Astra Intelligence Dashboard", layout="wide")

st.title("🧠 Astra Intelligence — Dashboard")

try:
    # Load data
    df = dashboard.load_data() if hasattr(dashboard, "load_data") else None
    if df is None or df.empty:
        st.warning("⚠️ No data available. Using placeholder mode.")

    # Render sidebar + summary
    if hasattr(dashboard, "render_sidebar"):
        dashboard.render_sidebar()

    if hasattr(dashboard, "render_summary"):
        dashboard.render_summary()

    # ✅ FIX — pass df into render_chart()
    if hasattr(dashboard, "render_chart"):
        dashboard.render_chart(df)
    else:
        st.warning("⚠️ Chart renderer missing.")

except Exception as e:
    import traceback

    st.error(f"⚠️ Dashboard failed: {e}")
    st.code(traceback.format_exc())
