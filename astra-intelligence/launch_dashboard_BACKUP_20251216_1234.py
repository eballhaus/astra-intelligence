import streamlit as st
import sys, os

# --- Path fix so Python can find the 'ui' package ---
# Add the parent directory of this script to sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.abspath(os.path.join(current_dir, '..'))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
