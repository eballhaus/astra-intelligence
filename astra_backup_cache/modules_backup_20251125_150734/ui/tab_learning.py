"""
Astra Learning Tab – Phase-90
--------------------------------
Displays and manages training activity for Astra models.
Updated for Guardian V6 compatibility.
"""

import streamlit as st
from datetime import datetime
from astra_modules.guardian.guardian_v6 import GuardianV6
import os
import pandas as pd

# Initialize Guardian
guardian = GuardianV6(os.path.dirname(__file__))

# Optional: path to your training log or checkpoint data
TRAIN_LOG = os.path.join(os.path.dirname(__file__), "../../astra_logs/training_log.csv")

def render_learning():
    """Render the Astra Learning Center tab"""
    st.title("🧠 Astra Intelligence – Learning Center")
    st.caption("Phase-90 • Guardian V6 Active")

    # Guardian heartbeat
    guardian.safe_run(lambda: st.success("✅ Guardian V6 verified and active."))

    # Display last training checkpoint if available
    checkpoint_file = os.path.join(os.path.dirname(__file__), "../../astra_phase_checkpoint.json")
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, "r") as f:
            last_checkpoint = f.read().strip()
        st.info(f"📘 Last Training Checkpoint Loaded:\n{last_checkpoint}")
    else:
        st.warning("No training checkpoint found.")

    # Show recent training activity log (if exists)
    if os.path.exists(TRAIN_LOG):
        try:
            df = pd.read_csv(TRAIN_LOG)
            st.subheader("📈 Recent Training Activity")
            st.dataframe(df.tail(10))
        except Exception as e:
            st.error(f"Error reading training log: {e}")
    else:
        st.caption("No training history available yet.")

    # Control buttons for retraining
    st.divider()
    st.subheader("Training Control Panel")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Start New Training Session"):
            guardian.safe_run(lambda: st.success(f"New training started at {datetime.now().strftime('%H:%M:%S')}"))
    with col2:
        if st.button("🧩 Analyze Last Model"):
            guardian.safe_run(lambda: st.info("Analyzing last trained model…"))

