import streamlit as st
from ui.dashboard.tab_dashboard_v7 import render_dashboard
st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
