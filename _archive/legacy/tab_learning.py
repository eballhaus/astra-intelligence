"""
🧠 Astra Learning Tab
------------------------------------------------
Visual interface for Astra’s reinforcement learning and memory systems.
"""

import os
import sys
from datetime import datetime

import pandas as pd
import streamlit as st


# --- Ensure project root path ---
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.abspath(os.path.join(current_dir, "../../.."))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- Guardian Import ---

# Optional imports for learning systems
try:
    from core.learning.learning_engine import LearningEngine
    from core.learning.replay_buffer import ReplayBuffer
except ImportError:
    guardian_core.guardian.log("⚠️ Learning modules not found — using safe mode.")


def render_learning_tab():
    """Render the Astra Learning Engine monitoring interface."""
    guardian = guardian_core
    guardian.guardian.log("🧠 Learning tab initialized successfully.")

    st.markdown(
        """
        <h2 style='text-align:center; color:#A7F3D0;'>🧠 Astra Learning Engine</h2>
        <p style='text-align:center; color:#9CA3AF;'>
            Monitoring reinforcement learning, replay buffer activity, and adaptive behavior.
        </p>
        <hr style='margin-top:1rem; border-color:rgba(255,255,255,0.1);'>
        """,
        unsafe_allow_html=True,
    )

    # --- Learning Engine Status ---
    st.subheader("🚀 Learning Engine Status")
    stats = {}
    try:
        engine = LearningEngine()
        if hasattr(engine, "get_status"):
            stats = engine.get_status()
            guardian.guardian.log("✅ LearningEngine connected.")
    except Exception as e:
        guardian.guardian.log(f"⚠️ LearningEngine unavailable: {e}", level="warning")

    cols = st.columns(3)
    with cols[0]:
        st.metric("Training Mode", stats.get("mode", "idle"))
    with cols[1]:
        st.metric("Episodes", stats.get("episodes", "N/A"))
    with cols[2]:
        st.metric(
            "Last Update", stats.get("last_update", datetime.now().strftime("%H:%M:%S"))
        )

    # --- Replay Buffer Overview ---
    st.subheader("🧩 Replay Buffer Overview")
    try:
        buffer = ReplayBuffer()
        df = (
            pd.DataFrame(buffer.sample(10))
            if hasattr(buffer, "sample")
            else pd.DataFrame()
        )
    except Exception as e:
        df = pd.DataFrame()
        guardian.guardian.log(f"⚠️ ReplayBuffer unavailable: {e}", level="warning")

    if not df.empty:
        st.dataframe(df, use_container_width=True, height=300)
    else:
        st.info("No replay buffer data available. Training may not have started.")

    # --- Guardian Health Monitor ---
    st.subheader("🛡️ Guardian Health Log")
    guardian_log_path = guardian_core.GUARDIAN_LOG_PATH
    if os.path.exists(guardian_log_path):
        with open(guardian_log_path, "r") as log_file:
            logs = log_file.readlines()[-25:]
        st.text_area("Recent Guardian Logs", "".join(logs), height=200)
    else:
        st.info("No Guardian logs available yet.")


if __name__ == "__main__":
    st.set_page_config(page_title="🧠 Astra Learning Tab", layout="wide")
    render_learning_tab()
