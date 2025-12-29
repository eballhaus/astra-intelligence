"""
Guardian Monitor Tab – Phase-101
--------------------------------
Displays Astra Guardian V6 and Sentinel health information in real time.
"""

import json
import os
from datetime import datetime

import streamlit as st


def render_guardian():
    st.title("🛡️ Astra Guardian – System Monitor")
    st.caption("Phase-101 • Real-time Sentinel and Guardian status")

    base_path = os.getcwd()
    log_path = os.path.join(base_path, "guardian_core.log")
    sentinel_report_path = os.path.join(base_path, "sentinel_report.json")

    # --- Sentinel Status ---
    st.subheader("🛰️ Sentinel Status")
    if os.path.exists(sentinel_report_path):
        try:
            with open(sentinel_report_path, "r") as f:
                data = json.load(f)
            st.success(f"✅ Last verified: {data.get('timestamp', 'unknown')}")
            st.json(data)
        except Exception as e:
            st.error(f"⚠️ Error reading sentinel report: {e}")
    else:
        st.warning(
            "Sentinel report not found yet. It will appear after first verification."
        )

    st.divider()

    # --- Guardian Log Viewer ---
    st.subheader("📜 Guardian Activity Log")
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                lines = f.readlines()[-20:]  # Last 20 lines
            for line in lines:
                if "initialized" in line:
                    st.success(line.strip())
                elif "error" in line.lower():
                    st.error(line.strip())
                elif "verification" in line.lower():
                    st.info(line.strip())
                else:
                    st.text(line.strip())
        except Exception as e:
            st.error(f"Failed to read Guardian log: {e}")
    else:
        st.warning("Guardian log file not found.")

    st.divider()

    # --- Manual Control ---
    st.subheader("⚙️ Manual Control")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🔁 Run Verification Now"):
            st.info("Running verification...")
            os.system("poetry run python verify_astra.py")
            st.success("Verification completed. Refresh to view updates.")

    with col2:
        if st.button("📂 Open Guardian Log"):
            st.info(f"Guardian log located at:\n{log_path}")

    st.caption(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
