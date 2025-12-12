# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Package
--------------------------------------
Unified dashboard namespace for AstraGlass interface.
Ensures all dashboard components import safely without blocking Streamlit startup.
🧠 Streamlit-safe edition — prevents reload loops by avoiding dynamic re-imports.
"""

from __future__ import annotations

import importlib
import sys

# ────────────────────────────────────────────────
# 🧱 One-time import guard (prevents reload loops)
# ────────────────────────────────────────────────
if getattr(sys.modules.get(__name__), "_astra_dashboard_initialized", False):
    # Already initialized — skip to prevent recursive reloads
    print("[Dashboard] ⚠️ Reload prevented — dashboard package already initialized.")
else:
    # Mark package as initialized
    sys.modules[__name__]._astra_dashboard_initialized = True

    # ────────────────────────────────────────────────
    # Primary Safe Imports (Runtime Function Access)
    # ────────────────────────────────────────────────
    try:
        from .dashboard_cards import render_empty_card, render_symbol_card
        from .dashboard_chart import render_chart
        from .dashboard_data import load_data
        from .dashboard_sidebar import render_sidebar
        from .dashboard_summary import render_summary
        from .theme_loader import load_theme
    except Exception as e:
        # Fallback mode (prevent Streamlit crash if any module fails)
        render_symbol_card = None
        render_empty_card = None
        render_chart = None
        load_data = None
        render_sidebar = None
        render_summary = None
        load_theme = None
        print(f"[Dashboard] ⚠️ Safe load mode activated — {e}")

    # ────────────────────────────────────────────────
    # Submodules (imported once and cached)
    # ────────────────────────────────────────────────
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
            _submodules[_mod] = importlib.import_module(
                f".{_mod}", __package__)
        except Exception as e:
            print(f"[Dashboard] ⚠️ Failed to import submodule {_mod}: {e}")

    # Cache submodules in globals for easy access
    globals().update(_submodules)

    # ────────────────────────────────────────────────
    # Exports (for both functions and submodules)
    # ────────────────────────────────────────────────
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

    print(
        "[Dashboard] ✅ Dashboard package initialized successfully (Streamlit-safe mode)."
    )
