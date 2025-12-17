import streamlit as st
import sys, os
# ensure Python can see the top-level folder that contains 'ui'
base_path = os.path.expanduser('~/Desktop/astra-intelligence')
if base_path not in sys.path:
    sys.path.insert(0, base_path)

from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
