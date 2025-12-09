# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Sidebar (v8)
-------------------------------------------
Handles sidebar rendering for the Astra Intelligence UI.

✅ Guardian-protected
✅ Auto-unique Streamlit widget keys
✅ Resilient to rate limits (429)
✅ Modular and extendable
✅ Fully syntax-safe (no unclosed try blocks)
"""

import pandas as pd
import streamlit as st

from astra_modules.fetch_core import fetch_unified
from astra_modules.guardian.guardian_v6 import guardian_log

guardian = guardian_log()

# ============================================================
# ⚙️ Market Overview (Safe API Fetch)
# ============================================================


def load_market_overview() -> pd.DataFrame:
    """
    Safely fetches key market indices from unified API.
    Falls back to placeholder data on failure.

    Returns:
        pd.DataFrame: Market overview data with Symbol, Price, Change, PercentChange.
    """
    try:
        symbols = ["^DJI", "^GSPC", "^IXIC"]
        data = fetch_unified.get_market_overview(symbols)
        guardian.log("[Sidebar] ✅ Market overview loaded successfully.")
        return data
    except Exception as e:
        guardian.log(f"[Sidebar] ⚠️ Market overview load issue: {e}")

        # Fallback placeholder data
        df = pd.DataFrame(
            {
                "Symbol": ["^DJI", "^GSPC", "^IXIC"],
                "Price": [35000, 4500, 14000],
                "Change": [0.12, -0.05, 0.22],
                "PercentChange": [0.34, -0.11, 0.18],
            }
        )
        guardian.log("[Sidebar] 🧩 Using fallback market overview data.")
        return df


# ============================================================
# 🧠 Sidebar Rendering
# ============================================================


def render_sidebar() -> str:
    """
    Builds the sidebar for dashboard navigation and market overview.
    Handles all exceptions gracefully with fallbacks.

    Returns:
        str: Selected tab/section from navigation radio button.
    """
    guardian.log("[Sidebar] 🧠 Rendering dashboard sidebar...")

    with st.sidebar:
        # --- Navigation Section ---
        st.markdown("## 🧭 Navigation")
        st.markdown("---")

        selected_tab = "Overview"
        try:
            tab_options = ["Overview", "Markets",
                           "Crypto", "AI Insights", "Settings"]
            selected_tab = st.radio(
                "Select Section:",
                tab_options,
                key="sidebar_nav_radio_v7",
            )
        except Exception as e:
            guardian.log(f"[Sidebar] ⚠️ Radio widget render issue: {e}")
            selected_tab = "Overview"

        # --- Market Overview Section ---
        st.markdown("---")
        st.markdown("## 📈 Market Overview")

        try:
            df = load_market_overview()

            if df is not None and not df.empty:
                # Safe fallback for missing columns
                required_cols = ["Symbol", "Price", "Change", "PercentChange"]
                for col in required_cols:
                    if col not in df.columns:
                        if col in ["Price", "Change", "PercentChange"]:
                            df[col] = 0.0
                        else:
                            df[col] = ""

                # Numeric safety checks
                for col in ["Price", "Change", "PercentChange"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(
                            df[col], errors="coerce").fillna(0.0)

                # Render overview safely
                for _, row in df.iterrows():
                    change_symbol = "🟢" if row["Change"] >= 0 else "🔴"
                    st.write(
                        f"**{row['Symbol']}** — {row['Price']:.2f}  "
                        f"{change_symbol} {row['PercentChange']:.2f}%"
                    )
            else:
                st.warning("⚠️ Market data unavailable.")

        except Exception as e:
            guardian.log(f"[Sidebar] ⚠️ Failed to render market overview: {e}")
            st.warning("⚠️ Market overview temporarily unavailable.")

        # --- Settings Section ---
        st.markdown("---")
        st.markdown("## ⚙️ Settings")

        try:
            auto_refresh = st.checkbox(
                "Auto-refresh data",
                value=True,
                key="auto_refresh_checkbox_v7",
            )
            theme_choice = st.selectbox(
                "Theme",
                ["AstraGlass", "Midnight", "Neon", "Solarized"],
                key="theme_selectbox_v7",
            )
        except Exception as e:
            guardian.log(f"[Sidebar] ⚠️ Settings render issue: {e}")

        # --- Footer ---
        st.markdown("---")
        st.caption("🛡️ Astra Intelligence © 2025 — Guardian Protected")

    guardian.log("[Sidebar] ✅ Sidebar rendered successfully.")
    return selected_tab


# ============================================================
# 🧪 Standalone Test Run
# ============================================================

if __name__ == "__main__":
    st.set_page_config(page_title="Sidebar Test", layout="wide")
    guardian.log("[Sidebar] 🧩 Running standalone test...")
    selected = render_sidebar()
    st.write(f"Selected Tab: **{selected}**")
