from astra_core.guardian.guardian_v6 import guardian

guardian = getattr(guardian_log, 'log', guardian_log)

import streamlit as st

st.title("Astra Streamlit Test")
st.write("If you can see this, Streamlit rendering works.")
