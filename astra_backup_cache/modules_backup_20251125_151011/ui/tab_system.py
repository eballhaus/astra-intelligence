"""
Astra Intelligence – System Health Monitor (Phase-90)
-----------------------------------------------------
Displays live system status from GuardianV6 and IntegrityBuilder.
Provides visibility into uptime, repair activity, and health metrics.
"""

import os
import time
from datetime import datetime
import streamlit as st
from pathlib import Path


def read_last_lines(filepath, n=10):
    """Read the last N lines of a log file safely."""
    try:
        path = Path(filepath)
        if not path.exists():
            return ["⚠️ Log file not found."]
        with open(path, "r") as f:
            lines = f.readlines()
        return lines[-n:] if lines else ["✅ Log is empty."]
    except Exception as e:
        return [f"⚠️ Failed to read {filepath}: {e}"]


def parse_repair_log(log_lines):
    """Extracts summary information from Integrity Builder log lines."""
    total_repairs = sum(1 for line in log_lines if "Re-created" in line)
    last_entry = log_lines[-1].strip() if log_lines else "No repair log entries."
    return total_repairs, last_entry


def render_system_health():
    """Render the system health dashboard for Guardian + Integrity."""
    base_path = os.path.dirname(__file__)
    guardian_log = os.path.join(base_path, "../../guardian_v6.log")
    repair_log = os.path.join(base_path, "../../astra_logs/integrity_repairs.log")

    st.title("🛡️ Astra System Health Monitor")
    st.caption("Phase-90 • GuardianV6 + IntegrityBuilder Status")

    # ----------------------------------------------------------------
    # Guardian Status Section
    # ----------------------------------------------------------------
    st.subheader("GuardianV6 Status")
    guardian_lines = read_last_lines(guardian_log, 10)
    guardian_active = any("GuardianV6 initialized" in l for l in guardian_lines)
    last_guardian_event = guardian_lines[-1].strip() if guardian_lines else "No log entries"

    col1, col2 = st.columns(2)
    col1.metric("Guardian Active", "✅ Yes" if guardian_active else "❌ No")
    col2.metric("Last Guardian Event", last_guardian_event[:60])

    with st.expander("📄 View Guardian Log"):
        st.text("\n".join(guardian_lines))

    # ----------------------------------------------------------------
    # Integrity Builder Section
    # ----------------------------------------------------------------
    st.subheader("IntegrityBuilder Status")
    repair_lines = read_last_lines(repair_log, 15)
    total_repairs, last_repair = parse_repair_log(repair_lines)
    last_run = next((l for l in reversed(repair_lines) if "Integrity Builder phase complete" in l), None)

    col3, col4 = st.columns(2)
    col3.metric("Repairs Performed", total_repairs)
    col4.metric("Last Repair Activity", last_run or "No recent integrity checks")

    with st.expander("📋 View Integrity Log"):
        st.text("\n".join(repair_lines))

    # ----------------------------------------------------------------
    # Summary Footer
    # ----------------------------------------------------------------
    st.markdown("---")
    st.caption(f"🕒 System Status Refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    st.caption("Powered by Astra Intelligence • Phase-90 Autonomous Mode")

