import streamlit as st
import sys, os
# Ensure Python can see the top-level dashboard modules
sys.path.append(os.path.expanduser('~/Desktop/astra-intelligence'))
from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
