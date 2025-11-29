# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Package
--------------------------------------
Unified dashboard namespace for AstraGlass interface.
Imports key modules and provides easy cross-references.
"""

from __future__ import annotations

# Safe imports for primary dashboard modules
try:
    from .dashboard_cards import render_cards
    from .dashboard_chart import render_chart
    from .dashboard_data import get_dashboard_data
    from .dashboard_sidebar import load_theme, render_sidebar
    from .dashboard_summary import render_summary
    from .tab_dashboard import render_dashboard_tab
except Exception:
    # Fallback mode (safe load)
    render_cards = render_chart = render_summary = render_sidebar = load_theme = None
    get_dashboard_data = render_dashboard_tab = None

__all__ = [
    "render_cards",
    "render_chart",
    "render_summary",
    "render_sidebar",
    "load_theme",
    "get_dashboard_data",
    "render_dashboard_tab",
]
