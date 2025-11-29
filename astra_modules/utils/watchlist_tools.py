# -*- coding: utf-8 -*-
"""
watchlist_tools.py — AstraGlass Watchlist Management
----------------------------------------------------
Handles persistent tracking of user-selected tickers.
"""

import json
import os
import streamlit as st

WATCHLIST_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "../../astra_watchlist.json"
))


def _load_watchlist() -> dict:
    """Load current watchlist JSON."""
    if not os.path.exists(WATCHLIST_PATH):
        return {"stocks": [], "crypto": []}
    try:
        with open(WATCHLIST_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"stocks": [], "crypto": []}


def _save_watchlist(data: dict) -> None:
    """Save updated watchlist."""
    try:
        with open(WATCHLIST_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        st.warning(f"⚠ Watchlist save failed: {e}")


def add_to_watchlist(symbol: str, category: str = "stocks") -> None:
    """Add a symbol to the watchlist."""
    data = _load_watchlist()
    cat = category.lower()
    if symbol not in data.get(cat, []):
        data[cat].append(symbol)
        _save_watchlist(data)


def remove_from_watchlist(symbol: str, category: str = "stocks") -> None:
    """Remove a symbol from the watchlist."""
    data = _load_watchlist()
    cat = category.lower()
    if symbol in data.get(cat, []):
        data[cat].remove(symbol)
        _save_watchlist(data)


def is_tracked(symbol: str, category: str = "stocks") -> bool:
    """Check if symbol is tracked."""
    data = _load_watchlist()
    return symbol in data.get(category.lower(), [])
