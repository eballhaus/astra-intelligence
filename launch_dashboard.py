import streamlit as st
from engine.learning_manager import start_background_learning
start_background_learning()
import asyncio
from engine.learning_manager import start_background_learning
import threading, asyncio
def start_background_learning():
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    loop.create_task(background_learning())
import sys, os

# --- Explicitly add the correct dashboard path ---
ui_path = os.path.expanduser('~/Desktop/astra-intelligence')
if ui_path not in sys.path:
    sys.path.insert(0, ui_path)
    print(f'📂 Added to sys.path: {ui_path}')

from ui.dashboard.tab_dashboard_v7 import render_dashboard

st.set_page_config(page_title='Astra Hydra Dashboard', layout='wide')
render_dashboard()
