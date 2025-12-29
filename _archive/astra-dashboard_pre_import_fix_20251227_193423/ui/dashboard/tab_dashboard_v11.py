import streamlit as st
import datetime
import json
import pandas as pd
from engine.data_orchestrator import fetch_live_data
from learning.funnel.astra_funnel import AstraFunnel
from core.audit.auditlock_v1 import verify

st.set_page_config(
    page_title="Astra Intelligence",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# === HEADER ===
st.markdown("""
<div style='text-align:center; padding:10px;'>
  <h1>🧠 Astra Intelligence</h1>
  <h4>Autonomous Prediction & Learning System</h4>
  <p><i>Live System Snapshot — {}</i></p>
</div>
""".format(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')), unsafe_allow_html=True)

st.divider()

# === SYSTEM STATUS GRID ===
col1, col2, col3 = st.columns(3)

with col1:
    st.markdown("### ⚙️ System Health")
    try:
        verify()
        st.success("All tracked files unchanged ✅")
    except Exception as e:
        st.error(f"Audit check failed: {e}")

with col2:
    st.markdown("### 🧬 Learning State")
    try:
        with open("learning_state.json") as f:
            state = json.load(f)
        st.json(state)
    except Exception:
        st.warning("Learning state unavailable.")

with col3:
    st.markdown("### 🛰 Sentinel Activity")
    try:
        import os
        logs = sorted(os.listdir("state/sentinel_logs"))[-5:]
        for log in logs:
            st.text(log)
    except Exception:
        st.info("No Sentinel logs found.")

st.divider()

# === LIVE FEED SECTION ===
st.markdown("## 📡 Live Market Feed")
try:
    live = fetch_live_data()
    if live:
        df_live = pd.DataFrame(live)
        st.dataframe(
            df_live,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No live data currently available.")
except Exception as e:
    st.error(f"Error fetching live data: {e}")

st.divider()

# === ASTRA FUNNEL ===
st.markdown("## 🔮 Astra Funnel Predictions")
try:
    f = AstraFunnel()
    preds = f.run()
    if preds:
        df_preds = pd.DataFrame(preds)
        # Highlight key metrics
        df_preds = df_preds[["symbol", "grade", "confidence", "summary", "price", "target", "pred_pct", "stop", "type"]]
        df_preds = df_preds.rename(columns={
            "symbol": "Symbol",
            "grade": "Grade",
            "confidence": "Confidence (%)",
            "summary": "Signal Summary",
            "price": "Price ($)",
            "target": "Target ($)",
            "pred_pct": "Pred. % Gain",
            "stop": "Stop ($)",
            "type": "Type"
        })
        st.dataframe(
            df_preds,
            use_container_width=True,
            hide_index=True
        )
    else:
        st.warning("No predictions returned by Astra Funnel.")
except Exception as e:
    st.error(f"Error running Astra Funnel: {e}")

st.divider()

# === FOOTER ===
st.markdown("""
<div style='text-align:center; opacity:0.7; padding-top:15px;'>
  <p>© Astra Intelligence — Guardian v7 | Funnel v11 | Sentinel Tier 2 | Autonomous Learning Core</p>
</div>
""", unsafe_allow_html=True)
