# import streamlit as st
import datetime
import json
from astra_dashboard.engine.data_orchestrator import fetch_live_data
from astra_dashboard.learning.funnel.astra_funnel import AstraFunnel
from astra_dashboard.core.audit.auditlock_v1 import verify

st.set_page_config(page_title="Astra Intelligence", layout="wide")

# --- Header ---
st.title("🧠 Astra Intelligence — Dashboard v10")
st.caption(f"Live System Snapshot — {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}")

# --- Section 1: System Health ---
st.subheader("⚙️ System Health")
col1, col2, col3 = st.columns(3)

with col1:
    st.write("**AuditLock Status:**")
    try:
        verify()
        st.success("All tracked files unchanged ✅")
    except Exception as e:
        st.error(f"Audit check failed: {e}")

with col2:
    st.write("**Learning State:**")
    try:
        with open("learning_state.json") as f:
            state = json.load(f)
            st.json(state)
    except Exception:
        st.warning("Learning state unavailable.")

with col3:
    st.write("**Sentinel Logs:**")
    try:
        import os
        logs = sorted(os.listdir("state/sentinel_logs"))[-3:]
        for log in logs:
            st.text(log)
    except Exception:
        st.info("No Sentinel logs found.")

# --- Section 2: Live Feed ---
st.subheader("📡 Live Feed")
try:
    live = fetch_live_data()
    if live:
        st.dataframe(live)
    else:
        st.warning("No live data available.")
except Exception as e:
    st.error(f"Error fetching live data: {e}")

# --- Section 3: Top Predictions ---
st.subheader("🔮 Astra Funnel Predictions")
try:
    f = AstraFunnel()
    preds = f.run()
    if preds:
        st.write(f"Showing {len(preds)} current predictions:")
        st.dataframe(preds)
    else:
        st.warning("No predictions returned by Astra Funnel.")
except Exception as e:
    st.error(f"Error running Astra Funnel: {e}")

# --- Section 4: Summary ---
st.divider()
st.caption("© Astra Intelligence — Autonomous Prediction Engine | Guardian v7 | Funnel v10 | Sentinel Tier 2")
