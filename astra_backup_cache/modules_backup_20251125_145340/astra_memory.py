# ======================================================================
# astra_memory.py — Phase 52 Ultra Safe Fallback
# Ensures memory-related imports never break the dashboard.
# ======================================================================

import streamlit as st

# ------------------------------------------------------------
# MEMORY SNAPSHOT LOAD / SAVE (SAFE FALLBACKS)
# ------------------------------------------------------------

def load_memory_snapshot():
    """
    Returns the last known learning/memory state.
    Prevents crashes if no memory file exists yet.
    """
    try:
        return st.session_state.get("astra_memory_snapshot", {})
    except Exception:
        return {}


def load_memory_snapshot_safe():
    """
    Fully safe wrapper used by Learning Tab.
    Never throws and always returns a dictionary.
    """
    try:
        snap = load_memory_snapshot()
        return snap if isinstance(snap, dict) else {}
    except Exception:
        return {}


def save_memory_snapshot(snapshot: dict):
    """
    Saves a lightweight memory snapshot for debugging or analytics.
    """
    try:
        st.session_state["astra_memory_snapshot"] = snapshot
    except Exception as e:
        print("save_memory_snapshot error:", e)


# ------------------------------------------------------------
# BASIC DIAGNOSTICS / SUMMARY (OPTIONAL)
# ------------------------------------------------------------

def get_memory_summary():
    """
    Returns a simple human-readable summary for UI display.
    """
    try:
        snap = st.session_state.get("astra_memory_snapshot", {})
        return {
            "entries": len(snap),
            "keys": list(snap.keys()),
            "status": "ok" if snap else "empty"
        }
    except Exception:
        return {"entries": 0, "keys": [], "status": "error"}
