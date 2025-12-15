import os
os.environ["ASTRA_FASTBOOT"]="1"
import streamlit as st
from datetime import datetime, timezone
from utils.guardian_lazy import get_guardian, is_guardian_ready
from utils.performance_profiler import Profiler
from core.cache_manager import CacheManager
from utils.async_loader import async_load_data
from ui.dashboard.dashboard_sidebar import render_sidebar
from ui.dashboard.dashboard_data import load_data
from ui.dashboard.dashboard_cards import render_symbol_card
from ui.dashboard.dashboard_chart import render_chart
from ui.dashboard.dashboard_summary import render_summary
from ui.dashboard.theme_loader import apply_theme

guardian=get_guardian()
st.set_page_config(page_title="Astra Intelligence Dashboard",
                   page_icon="🧠",layout="wide",
                   initial_sidebar_state="expanded")

def main():
    symbol=render_sidebar()
    apply_theme("AstraGlass")
    col1,col2,col3=st.columns([3,1,1])
    with col1: st.title("🧠 Astra Intelligence Dashboard")
    with col2: st.metric("Guardian","Active" if is_guardian_ready() else "⚠️")
    with col3: st.metric("Last Refresh",
                         datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
    cache=CacheManager()
    profiler=Profiler()
    with profiler.timer("dashboard_load"):
        try:
            data=async_load_data(lambda:load_data(symbol))
        except Exception as e:
            st.warning(f"⚠️ Data load failed: {e}")
            data=cache.get_last("dashboard_data")
    render_summary(data)
    render_symbol_card(data)
    render_chart(data)
    st.caption("⏱️ Load time tracked by Guardian Profiler.")
if __name__=="__main__":
    main()
