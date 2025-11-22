"""
tab_learning.py — Phase-90

Learning Center:
 • View ReplayBuffer size
 • Display recent memory samples
 • Inspect NeuralAgent weights
 • Show training logs
 • Trigger manual training
 • Guardian-safe

This is the main interface for monitoring Astra’s learning system.
"""

import streamlit as st
import numpy as np

from astra_modules.learning.replay_buffer import ReplayBuffer
from astra_modules.learning.continual_trainer import ContinualTrainer
from astra_modules.agents.neural_agent import NeuralAgent
from astra_modules.guardian.guardian_v3 import GuardianV3


def render_learning():

    st.markdown(
        "<h1 style='color:#F5F7FA;font-weight:700;'>Astra Intelligence — Learning Center</h1>",
        unsafe_allow_html=True
    )
    st.markdown(
        "<p style='color:#9DA5B4;margin-top:-12px;'>Phase-90 Online Learning Dashboard</p>",
        unsafe_allow_html=True
    )

    guardian = GuardianV3()

    # ======================================================================================
    # LOAD SYSTEM COMPONENTS
    # ======================================================================================
    buffer = guardian.safe_init(ReplayBuffer)
    neural = guardian.safe_init(NeuralAgent)
    trainer = guardian.safe_init(ContinualTrainer, neural, buffer)

    if buffer is None or neural is None or trainer is None:
        st.error("Failed to initialize learning modules.")
        return

    # ======================================================================================
    # REPLAY BUFFER OVERVIEW
    # ======================================================================================
    st.markdown("## 🧠 Replay Buffer Status")

    size = guardian.safe_run(buffer.size)
    st.metric("Stored Training Samples", size if size is not None else 0)

    # Show last N samples
    st.markdown("### Latest Samples")
    samples = guardian.safe_run(buffer.tail, 10) or []

    if len(samples) == 0:
        st.info("Replay buffer is empty. Predictions must run before training.")
    else:
        for s in samples:
            st.code(str(s), language="python")

    st.markdown("---")

    # ======================================================================================
    # NEURAL AGENT WEIGHTS
    # ======================================================================================
    st.markdown("## 🤖 Neural Model Weights")

    try:
        w = neural.weights
        b = neural.bias
        st.write("### Weights (12-vector):")
        st.code(np.array2string(w, precision=4), language="python")
        st.write("### Bias:")
        st.code(f"{b:.4f}")
    except Exception:
        st.error("Unable to load neural weights.")

    st.markdown("---")

    # ======================================================================================
    # TRAINING CONTROLS
    # ======================================================================================
    st.markdown("## 🔧 Training Controls")

    col1, col2 = st.columns([1, 2])

    with col1:
        if st.button("Run Training Step"):
            out = guardian.safe_run(trainer.train_step)
            if out:
                st.success("Training step completed.")
            else:
                st.warning("Training step failed or no data available.")

    with col2:
        st.markdown("""
        <div style='color:#ADB5BD;font-size:15px;'>
        • Uses last 256 samples<br>
        • Runs logistic update<br>
        • Updates model weights<br>
        • Automatically skips empty buffer<br>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # ======================================================================================
    # TRAINING LOGS (placeholder for Phase-100 expansion)
    # ======================================================================================
    st.markdown("## 📜 Learning Logs (Phase-100 Ready)")

    st.info("Training logs and metrics visualizations will be expanded in Phase-100.")
