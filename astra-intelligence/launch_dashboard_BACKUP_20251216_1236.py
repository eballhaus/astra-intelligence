import streamlit as st
import sys, os

# --- Path fix to include the top-level 'ui' folder ---
current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.abspath(os.path.join(current_dir, '..'))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

print(f'📂 Added project root to sys.path: {root_dir}')

from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
