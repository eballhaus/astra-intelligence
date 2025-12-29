# -*- coding: utf-8 -*-
"""
Astra Intelligence — Market Overview Summary Cards (v2.1 Stable)
----------------------------------------------------------------
Displays compact market summary cards with live index data.

Features:
✅ Fetches live market indices (S&P 500, NASDAQ, DOW)
✅ AstraAPI integration with graceful fallback
✅ AstraGlass visual styling
✅ Guardian-safe logging
✅ Auto-refresh compatible
✅ Proper error handling with placeholder data
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

import streamlit as st

from core.core.api_client import AstraAPI
from core.guardian.guardian_core import guardian

# ===================================================================
# 🎨 Visual Helper Functions
# ===================================================================


def get_color(change: float) -> str:
    """Return color based on change direction."""
    return "#4ade80" if change >= 0 else "#f87171"


def get_source_icon(source: str) -> str:
    """Return emoji for data source."""
    icon_map = {
        "live": "📡",
        "astra_api": "📡",
        "astra_api_live": "📡",
        "backend": "⚡",
        "astra_forecast": "🔮",
        "forecast": "🔮",
        "cache": "💾",
        "refetch": "🔄",
        "synthetic": "🧩",
        "mock": "🧩",
        "unified_fetch": "⚡",
        "fallback": "💤",
    }
    return icon_map.get(source, "❓")


def freshness_status(timestamp: Optional[str]) -> str:
    """Return freshness indicator based on timestamp."""
    try:
        if timestamp is None:
            return "⚠️ Unknown"
        import pandas as pd

        ts = pd.Timestamp(timestamp)
        diff = (datetime.now(timezone.utc) - ts).total_seconds() / 60.0
        return "✅ Fresh" if diff < 5 else f"⚠️ {diff:.0f}m old"
    except Exception:
        return "⚠️ Unknown"


# ===================================================================
# 📊 Market Data Loader
# ===================================================================


def fetch_index_data() -> Dict[str, Dict[str, Any]]:
    """
    Fetch live market indices via AstraAPI.
    Falls back to static data on failure.
    """
    indices = {
        "^GSPC": {"name": "S&P 500", "icon": "💹"},
        "^IXIC": {"name": "NASDAQ", "icon": "🧠"},
        "^DJI": {"name": "DOW JONES", "icon": "📈"},
    }
    data = {}

    try:
        try:
            api = AstraAPI()
        except Exception as e:
            guardian.log(f"[SummaryCards] ⚠️ AstraAPI init failed: {e}")
            return {}

        for symbol, meta in indices.items():
            try:
                quote = api.get_quote(symbol)
                if not quote or not isinstance(quote, dict):
                    guardian.log(
                        f"[SummaryCards] ⚠️ Invalid response for {meta['name']}"
                    )
                    continue

                price = float(quote.get("price", 0))
                change = float(quote.get("change", 0) or 0)
                source = quote.get("source", "live")

                data[symbol] = {
                    "name": meta["name"],
                    "icon": meta["icon"],
                    "price": price,
                    "change": change,
                    "source": source,
                }
                guardian.log(
                    f"[SummaryCards] ✅ Fetched {meta['name']} — {price:.2f} ({change:+.2f}%)"
                )

            except Exception as e:
                guardian.log(f"[SummaryCards] ⚠️ Fetch failed for {meta['name']}: {e}")

        if not data:
            guardian.log(
                "[SummaryCards] ⚠️ All index fetches failed — fallback mode active"
            )

        return data

    except Exception as e:
        guardian.log(f"[SummaryCards] 🚨 Index fetch critical error: {e}")
        return {}


# ===================================================================
# 💳 Main Renderer Function
# ===================================================================


def render_summary() -> None:
    """
    Render market summary cards with live data.
    Falls back to static data if API fails.
    """
    try:
        index_data = fetch_index_data()

        # Fallback to static data
        if not index_data:
            guardian.log("[SummaryCards] ⚠️ Using fallback index data")
            index_data = {
                "^GSPC": {
                    "name": "S&P 500",
                    "icon": "💹",
                    "price": 4850.32,
                    "change": 0.72,
                    "source": "fallback",
                },
                "^IXIC": {
                    "name": "NASDAQ",
                    "icon": "🧠",
                    "price": 15420.10,
                    "change": 0.58,
                    "source": "fallback",
                },
                "^DJI": {
                    "name": "DOW JONES",
                    "icon": "📈",
                    "price": 38150.00,
                    "change": 0.44,
                    "source": "fallback",
                },
            }

        cols = st.columns(len(index_data))
        for col, (symbol, meta) in zip(cols, index_data.items()):
            with col:
                change = meta.get("change", 0)
                color = get_color(change)
                source = meta.get("source", "unknown")
                source_icon = get_source_icon(source)

                st.markdown(
                    f"""
                    <div class='astra-box' style='text-align:center;min-height:160px;
                    display:flex;flex-direction:column;justify-content:center;'>
                        <div style='font-size:2rem;margin-bottom:0.75rem;'>{meta['icon']}</div>
                        <div style='color:#A7F3D0;font-weight:700;font-size:1rem;margin-bottom:0.5rem;'>
                            {meta['name']}
                        </div>
                        <div style='color:#E5E7EB;font-size:1.4rem;font-weight:bold;margin-bottom:0.5rem;'>
                            {meta['price']:,.2f}
                        </div>
                        <div style='color:{color};font-weight:700;font-size:1.1rem;margin-bottom:0.75rem;'>
                            {change:+.2f}%
                        </div>
                        <div style='font-size:0.75rem;color:#6B7280;border-top:1px solid rgba(255,255,255,0.05);
                        padding-top:0.5rem;'>
                            {source_icon} {source}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

        now = datetime.now(timezone.utc)
        st.markdown(
            f"""
            <div style='color:#6B7280;font-size:0.75rem;margin-top:1rem;text-align:center;'>
                🕒 Last updated: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}
            </div>
            """,
            unsafe_allow_html=True,
        )

        guardian.log("[SummaryCards] ✅ Summary cards rendered successfully")

    except Exception as e:
        guardian.log(f"[SummaryCards] 🚨 Render error: {e}")
        st.error(f"⚠️ Summary render failed: {str(e)[:120]}")


# ===================================================================
# 🧪 Standalone Test
# ===================================================================

if __name__ == "__main__":
    guardian.log("[SummaryCards] 🔍 Running self-test...")

    st.set_page_config(page_title="Market Summary Test", page_icon="📊", layout="wide")

    st.markdown(
        """
        <style>
        .astra-box {
            background: rgba(15, 23, 42, 0.6);
            border: 1px solid rgba(167, 243, 208, 0.15);
            border-radius: 12px;
            padding: 1.25rem;
            backdrop-filter: blur(8px);
            transition: all 0.3s ease-in-out;
        }
        .astra-box:hover {
            border-color: rgba(167, 243, 208, 0.4);
            background: rgba(15, 23, 42, 0.8);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("📊 Astra Intelligence — Market Summary Test")
    render_summary()
