# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Package
--------------------------------------
Fully Streamlit-safe initialization with zero I/O at import time.
Prevents crashes caused by closed stdout/stderr descriptors.
"""

from __future__ import annotations

import importlib
import sys
import traceback


# ────────────────────────────────────────────────
# 🧱 Safe in-memory logger
# ────────────────────────────────────────────────
def safe_log(message: str) -> None:
    """Store messages in memory to avoid I/O errors."""
    _astra_dashboard_log = getattr(sys.modules[__name__], "_astra_dashboard_log", [])
    _astra_dashboard_log.append(message)
    sys.modules[__name__]._astra_dashboard_log = _astra_dashboard_log


def safe_traceback_store() -> None:
    """Store traceback safely in memory without writing to stderr."""
    try:
        tb = traceback.format_exc()
        _astra_dashboard_errors = getattr(
            sys.modules[__name__], "_astra_dashboard_errors", []
        )
        _astra_dashboard_errors.append(tb)
        sys.modules[__name__]._astra_dashboard_errors = _astra_dashboard_errors
    except Exception:
        pass  # Suppress all secondary exceptions safely


# ────────────────────────────────────────────────
# 🧱 One-time import guard
# ────────────────────────────────────────────────
if getattr(sys.modules.get(__name__), "_astra_dashboard_initialized", False):
    safe_log("[Dashboard] ⚠️ Reload prevented — dashboard package already initialized.")
else:
    sys.modules[__name__]._astra_dashboard_initialized = True

    # ────────────────────────────────────────────────
    # Primary Safe Imports
    # ────────────────────────────────────────────────
    try:
        from .dashboard_cards import render_empty_card, render_symbol_card
        from .dashboard_chart import render_chart
        from .dashboard_data_safe_patch import load_data
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
        safe_log(f"[Dashboard] ⚠️ Safe load mode activated — {e}")
        safe_traceback_store()

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
            _submodules[_mod] = importlib.import_module(f".{_mod}", __package__)
        except Exception as e:
            safe_log(f"[Dashboard] ⚠️ Failed to import submodule {_mod}: {e}")
            safe_traceback_store()

    globals().update(_submodules)

    __all__ = [
        "render_symbol_card",
        "render_empty_card",
        "render_chart",
        "load_data",
        "render_sidebar",
        "render_summary",
        "load_theme",
        "dashboard_cards",
        "dashboard_chart",
        "dashboard_data",
        "dashboard_sidebar",
        "dashboard_summary",
        "theme_loader",
    ]

    safe_log(
        "[Dashboard] ✅ Dashboard package initialized successfully (Streamlit-safe mode)."
    )
