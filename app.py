<<<<<<< Updated upstream
<<<<<<< Updated upstream
# app.py
# Astra Intelligence Phase-90 Main Application

import os
import streamlit as st
from astra_modules.guardian.guardian_v6 import GuardianV6

# UI tab imports
from astra_modules.ui.tab_dashboard import render_dashboard
from astra_modules.ui.tab_predictions import render_predictions
from astra_modules.ui.tab_learning import render_learning

# Optional: from astra_modules.ui.tab_monitoring import render_monitoring


def main():
    """Launch Astra Intelligence Phase-90 Streamlit application."""

    # ---------- GLOBAL PAGE CONFIG ----------
    st.set_page_config(
        page_title="Astra Intelligence – Phase-90",
        page_icon="🚀",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # ---------- GUARDIAN INITIALIZATION ----------
    base_path = os.path.dirname(os.path.abspath(__file__))
    guardian = GuardianV6(base_path)
    guardian.safe_run(lambda: print(f">>> GuardianV6 initialized at {base_path}"))

    # ---------- SIDEBAR NAVIGATION ----------
    st.sidebar.markdown(
        """
        <h2 style='color:#6FA3EF;'>🧭 Navigation</h2>
        """,
        unsafe_allow_html=True,
    )

    selected_tab = st.sidebar.radio(
        "Select a tab:",
        ["Dashboard", "Predictions", "Learning", "Monitoring"],
        index=0,
    )

    st.sidebar.markdown(
        "<p style='color:#6FA3EF;font-weight:600;'>🛡️ Guardian V6 verified system integrity.</p>",
        unsafe_allow_html=True,
    )

    # ---------- MAIN ROUTING ----------
    if selected_tab == "Dashboard":
        render_dashboard()
    elif selected_tab == "Predictions":
        render_predictions()
    elif selected_tab == "Learning":
        render_learning()
    elif selected_tab == "Monitoring":
        st.info("Monitoring module under development for Phase-100.")
    else:
        st.error("Invalid tab selection.")

    # ---------- FOOTER ----------
    st.markdown(
        """
        <hr>
        <div style='text-align:center;color:#6FA3EF;'>
            © 2025 Astra Intelligence • Phase-90 Framework
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------- ENTRY POINT ----------
if __name__ == "__main__":
=======
"""
Astra Intelligence – Phase-101 Autonomous Boot
----------------------------------------------
Fully autonomous boot integration for Guardian V6 and Astra Stability Sentinel.
Ensures self-healing, background monitoring, and automatic environment verification.
"""

import os
import sys
import threading
import subprocess
import time
import streamlit as st

# =============================================================================
#  Environment setup
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# =============================================================================
#  Auto-start Guardian V6 and Astra Sentinel
# =============================================================================

=======
"""
Astra Intelligence – Phase-101 Autonomous Boot
----------------------------------------------
Fully autonomous boot integration for Guardian V6 and Astra Stability Sentinel.
Ensures self-healing, background monitoring, and automatic environment verification.
"""

import os
import sys
import threading
import subprocess
import time
import streamlit as st

# =============================================================================
#  Environment setup
# =============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

# =============================================================================
#  Auto-start Guardian V6 and Astra Sentinel
# =============================================================================

>>>>>>> Stashed changes
def _launch_guardian():
    """Launch Guardian V6 in silent background mode."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "astra_modules/guardian/guardian_v6.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("🛡️ Guardian V6 auto-launched (silent mode).")
    except Exception as e:
        print(f"⚠️ Failed to launch Guardian V6: {e}")

def _launch_sentinel():
    """Launch the Astra Stability Sentinel watchdog."""
    try:
        subprocess.Popen(
            [sys.executable, os.path.join(BASE_DIR, "astra_modules/system/astra_sentinel.py")],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        print("🛰️ Astra Sentinel active.")
    except Exception as e:
        print(f"⚠️ Failed to launch Sentinel: {e}")

# Start both background threads non-blocking
threading.Thread(target=_launch_guardian, daemon=True).start()
time.sleep(2)
threading.Thread(target=_launch_sentinel, daemon=True).start()

# =============================================================================
#  Streamlit UI Imports
# =============================================================================

from astra_modules.ui.tab_dashboard import render_dashboard
from astra_modules.ui.tab_learning import render_learning
from astra_modules.ui.tab_guardian import render_guardian

# =============================================================================
#  Streamlit App Layout
# =============================================================================

def main():
    st.set_page_config(
        page_title="Astra Intelligence – Market Dashboard",
        page_icon="🧠",
        layout="wide"
    )

    st.sidebar.title("⚙️ Navigation")
    section = st.sidebar.radio("Go to section:", ["📊 Dashboard", "🧠 Learning Center", "🛡️ Guardian Monitor"])

    if section == "📊 Dashboard":
        render_dashboard()
    elif section == "🧠 Learning Center":
        render_learning()
    elif section == "🛡️ Guardian Monitor":
        render_guardian()

    st.sidebar.markdown("---")
    st.sidebar.caption("Astra Phase-101 • Autonomous Boot Mode")

# =============================================================================
#  Entrypoint
# =============================================================================

if __name__ == "__main__":
    print("🚀 Astra Intelligence App starting...")
<<<<<<< Updated upstream
>>>>>>> Stashed changes
=======
>>>>>>> Stashed changes
    main()

