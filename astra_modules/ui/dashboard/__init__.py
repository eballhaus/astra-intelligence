# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Package
--------------------------------------
Unified dashboard namespace for AstraGlass interface.
Ensures all dashboard components import safely without blocking Streamlit startup.
"""

from __future__ import annotations

# Safe imports for primary dashboard modules
try:
    from .dashboard_cards import render_symbol_card, render_empty_card
    from .dashboard_chart import render_chart
    from .dashboard_data import load_data
    from .dashboard_sidebar import render_sidebar
    from .dashboard_summary import render_summary
    from .theme_loader import load_theme
except Exception as e:
    # Fallback mode (safe load, prevents Streamlit crash)
    render_symbol_card = None
    render_empty_card = None
    render_chart = None
    load_data = None
    render_sidebar = None
    render_summary = None
    load_theme = None

__all__ = [
    "render_symbol_card",
    "render_empty_card",
    "render_chart",
    "load_data",
    "render_sidebar",
    "render_summary",
    "load_theme",
]
