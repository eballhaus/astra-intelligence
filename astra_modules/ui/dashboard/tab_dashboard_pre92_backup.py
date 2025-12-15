# -------------------------------------------------------------------
# 🌌 ASTRA DASHBOARD v4.4 — Optimized Version (Phase 6 Auto-Swap Ready)
# -------------------------------------------------------------------

from core.cache_manager import CacheManager
from astra_modules.utils.guardian_lazy import get_guardian, is_guardian_ready
import os

import streamlit as st

os.environ["ASTRA_FASTBOOT"] = "1"


# Initialize Guardian (non-blocking proxy)
guardian = get_guardian()


# Safe logger: forwards to real GuardianCore once it's ready
def guardian_log(msg):
    try:
        from astra_modules.utils.guardian_lazy import is_guardian_ready

        if is_guardian_ready():
            core = getattr(guardian, "_core", None)
            if core and hasattr(core, "guardian_log"):
                return core.guardian_log(msg)
        # fallback while loading
        print("[LazyGuardian]", msg)
    except Exception as e:
        print(f"[GuardianProxy] Logging error: {e}")


# Optional: visual indicator of GuardianCore readiness
if is_guardian_ready():
    st.sidebar.success("Guardian fully loaded ✅")
else:
    st.sidebar.info("Loading GuardianCore… ⏳")


# -------------------------------------------------------------------
# 🧠 MAIN DASHBOARD FUNCTIONS
# -------------------------------------------------------------------


def render_header():
    st.title("🌌 Astra Intelligence Dashboard")
    st.caption("Fast, intelligent, multi-agent market intelligence system.")


def render_equities_section():
    st.subheader("📈 Equities Overview")
    st.write("Equities section will display top stock opportunities.")
    # Placeholder for equities content
    cached_equities = CacheManager.get("cached_equities")
    if cached_equities:
        st.write("✅ Loaded cached equities data.")


def render_crypto_section():
    st.subheader("🪙 Crypto Overview")
    st.write("Top-ranked crypto assets by Astra Intelligence.")
    cached_crypto = CacheManager.get("cached_crypto")
    if cached_crypto:
        st.write("✅ Loaded cached crypto data.")


def render_market_overview_chart():
    st.subheader("🌐 Market Overview")
    st.write("Charts and sentiment overview go here.")


def render_advanced_chart_section():
    st.subheader("📊 Advanced Charting")
    st.write("Deep visual analytics powered by Astra Intelligence.")


def render_summary():
    st.subheader("🧭 Summary")
    st.write("End of dashboard summary and metrics.")


def render_footer():
    st.markdown("---")
    st.caption("Astra Intelligence © 2025 | Engine v4.4 | Performance Optimized")


def main():
    guardian_log("[Dashboard] 🚀 Astra Dashboard v4.4 Live")
    render_header()
    render_equities_section()
    render_crypto_section()
    render_market_overview_chart()
    render_advanced_chart_section()
    render_summary()
    render_footer()
    guardian_log("[Dashboard] ✅ Dashboard Rendered Successfully")


# -------------------------------------------------------------------
# 🚀 ENTRY POINT (FAST LOAD OPTIMIZED)
# -------------------------------------------------------------------
if __name__ == "__main__":
    import streamlit as st

    from astra_modules.engine.preload_thread import start_async_preload

    start_async_preload()
    from astra_modules.utils.deferred_imports import deferred_import

    for mod in ["torch", "transformers", "sklearn", "numpy"]:
        deferred_import(mod)

    try:
        # 🚀 Faster startup — disable automatic loop start for now
        # toggle_background_learning(on=True, interval_minutes=5)
        main()

        # 🧭 Manual background loop control (on-demand)
        st.divider()
        st.subheader("⚙️ Background Learning Control")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Start Background Learning"):
                toggle_background_learning(on=True)
        with col2:
            if st.button("⏹ Stop Background Learning"):
                toggle_background_learning(on=False)

    except Exception as e:
        guardian_log(f"[Dashboard] 🚨 Fatal dashboard error: {e}")
        st.error("🚨 Dashboard failed to render. Check Astra logs.")

# -------------------------------------------------------------------
# 🧠 BACKGROUND LEARNING CONTROL
# -------------------------------------------------------------------
_background_loop = None  # keep global reference


def _lazy_import_background_loop():
    """Import BackgroundLoop only when needed (lazy load)."""
    from astra_modules.engine.background_loop import BackgroundLoop

    return BackgroundLoop


def toggle_background_learning(on: bool = True, interval_minutes: int = 10):
    """
    Start or stop the background learning loop (lazy import, safe).
    """
    import streamlit as st

    global _background_loop

    BackgroundLoop = _lazy_import_background_loop()

    if on:
        if _background_loop and getattr(_background_loop, "running", False):
            st.info("ℹ️ Background learning already running.")
            return
        _background_loop = BackgroundLoop(interval_minutes=interval_minutes)
        _background_loop.start()
        st.success(
            f"✅ Background learning started (interval: {interval_minutes} min)")
    else:
        if _background_loop:
            _background_loop.stop()
            st.warning("⏹ Background learning stopped.")
        else:
            st.info("ℹ️ No background learning loop active.")
