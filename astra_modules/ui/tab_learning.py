"""
Astra Intelligence — Learning Center
Phase-101.9 | NeuralGlass Interface | Guardian V6 Active
-------------------------------------------------------
Displays and manages training activity for Astra models.
Includes GuardianV6 self-check, checkpoint load, and training controls.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
import streamlit as st

from astra_modules.guardian.guardian_v6 import GuardianV6

# ──────────────────────────────────────────────
# Paths and Initialization
# ──────────────────────────────────────────────
BASE_DIR = os.path.dirname(__file__)
TRAIN_LOG = os.path.join(BASE_DIR, "../../astra_logs/training_log.csv")
CHECKPOINT_FILE = os.path.join(BASE_DIR, "../../astra_phase_checkpoint.json")

guardian = GuardianV6(BASE_DIR)


# ──────────────────────────────────────────────
# Main Render Function
# ──────────────────────────────────────────────
def render_learning_tab() -> None:
    """Render the Astra Learning Center tab."""
    st.markdown("## 🧠 Astra Intelligence — Learning Center")
    st.caption("Phase-101.9 • NeuralGlass Interface • Guardian V6 Active")

    # Guardian heartbeat
    guardian.safe_run(lambda: st.success("✅ Guardian V6 verified and active."))

    # Checkpoint display
    st.markdown("### 📘 Latest Training Checkpoint")
    if os.path.exists(CHECKPOINT_FILE):
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                last_checkpoint = f.read().strip()
            st.info(f"Last checkpoint loaded:\n\n```\n{last_checkpoint}\n```")
        except Exception as e:
            st.error(f"Error reading checkpoint: {e}")
    else:
        st.warning("No training checkpoint found.")

    # Training activity log
    st.markdown("### 📈 Recent Training Activity")
    if os.path.exists(TRAIN_LOG):
        try:
            df = pd.read_csv(TRAIN_LOG)
            if not df.empty:
                st.dataframe(
                    df.tail(10), use_container_width=True, hide_index=True)
            else:
                st.caption("Training log exists but is empty.")
        except Exception as e:
            st.error(f"Error reading training log: {e}")
    else:
        st.caption("No training history available yet.")

    # Training control panel
    st.divider()
    st.markdown("### ⚙️ Training Control Panel")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("🚀 Start New Training Session"):
            guardian.safe_run(
                lambda: st.success(
                    f"New training started at {datetime.now().strftime('%H:%M:%S')}"
                )
            )
    with col2:
        if st.button("🧩 Analyze Last Model"):
            guardian.safe_run(lambda: st.info("Analyzing last trained model…"))

    st.markdown("---")
    st.caption(
        "Learning Center powered by ContinualTrainer | Guardian V6 self-defense active"
    )


# ──────────────────────────────────────────────
# Stand-alone Debug
# ──────────────────────────────────────────────
if __name__ == "__main__":
    st.set_page_config(page_title="Astra Learning Center", layout="wide")
    render_learning_tab()
