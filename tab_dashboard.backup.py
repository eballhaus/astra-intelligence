"""
Astra Intelligence - Dashboard Tab
----------------------------------
Main orchestrator for the Astra dashboard view.
Loads data, renders charts, and displays Astra AI forecasts & rankings.

Features:
• Unified data fetch from dashboard_data.py
• Interactive charts (dashboard_chart.py)
• Symbol cards with forecast and rank metrics
• Smart layout and error handling
"""

import streamlit as st

from astra_core.ui.dashboard.dashboard_cards import render_symbol_card
from astra_core.ui.dashboard.dashboard_chart import render_chart
from astra_core.ui.dashboard.dashboard_summary import render_summary  # optional

st.set_page_config(
    page_title="Astra Intelligence Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


def app():
    """Main function for the Astra Dashboard tab."""

    st.title("🧠 Astra Intelligence Dashboard")
    st.caption("Autonomous AI-driven Market Intelligence System")

    st.write("✅ Streamlit rendering confirmed — Astra dashboard context active.")

    # Sidebar Configuration
    st.sidebar.header("Dashboard Controls")

    default_symbols = ["AAPL", "MSFT", "TSLA", "BTC/USD", "ETH/USD"]
    symbols_input = st.sidebar.text_area(
        "Enter symbols (comma-separated):",
        value=", ".join(default_symbols),
        help="Example: AAPL, MSFT, BTC/USD, ETH/USD",
    )

    symbols = [s.strip().upper() for s in symbols_input.split(",") if s.strip()]

    refresh = st.sidebar.button(
        "🔄 Refresh Data", help="Fetch latest market & forecast data"
    )

    if not symbols:
        st.warning("Please enter at least one symbol to begin.")
        return

    st.info(f"Loading data for: {', '.join(symbols)}")

    # === Load Data ===
    try:
        # data_bundles = load_dashboard_data(symbols=symbols, include_forecast=True)
        data_bundles = {}
    except Exception as e:
        st.error(f"❌ Failed to load dashboard data: {e}")
        return

    if not data_bundles:
        st.warning(
            "No data available. Please check your API connections or symbol names."
        )
        return

    # === Summary Section (Optional) ===
    try:
        if "render_summary" in globals():
            render_summary(data_bundles)
    except Exception as e:
        st.warning(f"⚠️ Summary render failed: {e}")

    # === Main Display ===
    for symbol, data_bundle in data_bundles.items():
        st.markdown(f"## 📈 {symbol}")

        try:
            render_chart(data_bundle)
        except Exception as e:
            st.error(f"Chart rendering failed for {symbol}: {e}")

        try:
            render_symbol_card(symbol, data_bundle)
        except Exception as e:
            st.warning(f"Card rendering failed for {symbol}: {e}")

            # === Streamlit Entry Point ===
            if "streamlit" in __name__:
                app()
            elif __name__ == "__main__":
                app()
