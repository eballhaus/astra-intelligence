import streamlit as st
from ui.dashboard.dashboard_data import load_data

st.set_page_config(page_title="Astra Diagnostic Dashboard", layout="wide")
st.title("🧠 Astra Diagnostic Dashboard")

try:
    df = load_data("AAPL")
    if df is not None and not df.empty:
        st.success(f"✅ Data loaded: {len(df)} rows")
        st.dataframe(df.head())
    else:
        st.warning("⚠️ DataFrame is empty — backend link may be failing.")
except Exception as e:
    st.error(f"❌ Error loading data: {e}")
