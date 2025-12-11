# ============================================================
# Astra Intelligence — Dashboard Package (Fixed Initialization)
# ============================================================

from __future__ import annotations
import importlib
import sys

# -------------------------------------------------------------------
# 🧩 Guardian Boot (Unified Logging System)
# -------------------------------------------------------------------
try:
    from astra_core.guardian.guardian_v6 import guardian_boot, guardian

    guardian_boot()
    guardian.log("[Dashboard Init] ✅ Guardian v6 initialized successfully.")
except Exception as e:
    guardian = None
    print(f"[Dashboard Init] ⚠️ Guardian import failed: {e}")

# -------------------------------------------------------------------
# 📦 Astra Dashboard Package Docstring
# -------------------------------------------------------------------
"""
Astra Intelligence — Dashboard Package
--------------------------------------
Unified dashboard namespace for AstraGlass interface.
Ensures all dashboard components import safely without blocking Streamlit startup.
🧠 Streamlit-safe edition — prevents reload loops by avoiding dynamic re-imports.
"""

# -------------------------------------------------------------------
# 🧱 One-time import guard (prevents reload loops)
# -------------------------------------------------------------------
if getattr(sys.modules.get(__name__), "_astra_dashboard_initialized", False):
    print("[Dashboard] ⚠️ Reload prevented — dashboard package already initialized.")
else:
    sys.modules[__name__]._astra_dashboard_initialized = True

    # -------------------------------------------------------------------
    # 🔧 Safe Imports (core rendering functions)
    # -------------------------------------------------------------------
    try:
        from .dashboard_cards import render_empty_card, render_symbol_card
        from .dashboard_chart import render_chart
        from .dashboard_data import load_data
        from .dashboard_sidebar import render_sidebar
        from .dashboard_summary import render_summary
        from .theme_loader import load_theme

    except Exception as e:
        render_symbol_card = None
        render_empty_card = None
        render_chart = None
        load_data = None
        render_sidebar = None
        render_summary = None
        load_theme = None

        if guardian:
            guardian.log(f"[Dashboard] ⚠️ Safe load mode activated — {e}")
        else:
            print(f"[Dashboard] ⚠️ Safe load mode activated — {e}")

    # -------------------------------------------------------------------
    # 🧠 Submodules (imported once and cached)
    # -------------------------------------------------------------------
    _submodules = {
        "dashboard_cards": None,
        "dashboard_chart": None,
        "dashboard_data": None,
        "dashboard_sidebar": None,
        "dashboard_summary": None,
        "theme_loader": None,
    }

    for _mod in _submodules.keys():
        try:
            _submodules[_mod] = importlib.import_module(f".{_mod}", __package__)
        except Exception as e:
            if guardian:
                guardian.log(f"[Dashboard] ⚠️ Failed to import submodule {_mod}: {e}")
            else:
                print(f"[Dashboard] ⚠️ Failed to import submodule {_mod}: {e}")

    globals().update(_submodules)

    # -------------------------------------------------------------------
    # ✅ Exported Symbols
    # -------------------------------------------------------------------
    __all__ = [
        # Functions
        "render_symbol_card",
        "render_empty_card",
        "render_chart",
        "load_data",
        "render_sidebar",
        "render_summary",
        "load_theme",
        # Submodules
        "dashboard_cards",
        "dashboard_chart",
        "dashboard_data",
        "dashboard_sidebar",
        "dashboard_summary",
        "theme_loader",
    ]

    # -------------------------------------------------------------------
    # 🧩 Final Confirmation
    # -------------------------------------------------------------------
    if guardian:
        guardian.log("[Dashboard] ✅ Dashboard package initialized successfully (Streamlit-safe mode).")
    print("[Dashboard] ✅ Dashboard package initialized successfully (Streamlit-safe mode).")

# === Safe Mode Override Patch ===
try:
    import builtins
    if getattr(builtins, "DASHBOARD_SAFE_MODE", None):
        builtins.DASHBOARD_SAFE_MODE = False
        print("[DashboardCompat] ⚙️ Safe mode override: dashboard functions restored to normal mode.")
except Exception as e:
    print("[DashboardCompat] ⚠️ Failed to override safe mode:", e)

# === Astra Dashboard Safe Mode Override ===
try:
    import builtins
    # Disable global safe mode flag if set
    builtins.DASHBOARD_SAFE_MODE = False

    # Reimport real dashboard components to override fallbacks
    from astra_core.ui.dashboard import (
        dashboard_sidebar,
        dashboard_data,
        dashboard_cards,
    )
    print("[DashboardCompat] 🧠 Safe mode override — restoring real dashboard functions.")

    # Replace any None placeholders with the real ones
    builtins.render_sidebar = getattr(dashboard_sidebar, "render_sidebar", None)
    builtins.load_data = getattr(dashboard_data, "load_data", None)
    builtins.render_symbol_card = getattr(dashboard_cards, "render_symbol_card", None)
except Exception as e:
    print("[DashboardCompat] ⚠️ Failed to override dashboard safe mode:", e)
