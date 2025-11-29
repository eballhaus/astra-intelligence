from astra_modules.ui.dashboard.tab_dashboard import render_dashboard
import streamlit as st

from astra_modules.ui.dashboard.dashboard_cards import render_cards
from astra_modules.ui.dashboard.dashboard_chart import render_chart
from astra_modules.ui.dashboard.dashboard_data import load_dashboard_data
from astra_modules.ui.dashboard.dashboard_sidebar import render_sidebar
from astra_modules.ui.dashboard.dashboard_summary import render_summary
from astra_modules.ui.dashboard.theme_loader import apply_theme

# ──────────────────────────────────────────────
# ASTRA INTELLIGENCE — PHASE-105
# AstraGlass Neural Dashboard (Stable Dual-Mode)
# ──────────────────────────────────────────────


def render_dashboard():
    # ──────────────────────────────────────────────
    # Astra Intelligence Dashboard
    # Phase-105 — Stable Theme & Layout
    # ──────────────────────────────────────────────

    # Configure Streamlit layout
    st.set_page_config(
        page_title="Astra Intelligence Dashboard", layout="wide")

    # Apply unified Astra theme (controlled in theme_loader.py)
    apply_theme()  # "dark" mode by default, can change inside theme_loader if needed

    # Render sidebar with AstraGlass styling
    render_sidebar()

    # Retrieve dashboard data
    data = load_dashboard_data()

    # Layout Styling (independent scrolls + glass panels)
    st.markdown(
        """
        <style>
        .glass-panel {
            background: rgba(255,255,255,0.05);
            backdrop-filter: blur(12px);
            border-radius: 16px;
            padding: 1rem 1.2rem;
            height: 82vh;
            overflow-y: auto;
            box-shadow: 0 0 20px rgba(0,0,0,0.25);
        }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb {
            background: rgba(255,255,255,0.15);
            border-radius: 6px;
        }
        .section-title {
            font-size: 1.3rem;
            font-weight: 600;
            color: #5EEAD4;
            margin-bottom: 0.6rem;
        }
        .guardian-footer {
            margin-top: 2rem;
            text-align: center;
            font-size: 0.9rem;
            color: rgba(255,255,255,0.6);
        }
        .card-hover {
            transition: all 0.2s ease-in-out;
            border-radius: 12px;
        }
        .card-hover:hover {
            transform: scale(1.03);
            background: rgba(255,255,255,0.07);
        }
        </style>
    """,
        unsafe_allow_html=True,
    )

    # Create 3 columns (Stocks | Crypto | Chart + Summary)
    col1, col2, col3 = st.columns([1, 1, 2], gap="large")

    # 🏦 Stocks column
    with col1:
        st.markdown(
            '<div class="section-title">🏦 Stocks</div>', unsafe_allow_html=True
        )
        st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
        render_cards(data.get("stocks", []), category="stocks")
        st.markdown("</div>", unsafe_allow_html=True)

    # 💰 Crypto column
    with col2:
        st.markdown(
            '<div class="section-title">💰 Crypto</div>', unsafe_allow_html=True
        )
        st.markdown('<div class="glass-panel">', unsafe_allow_html=True)
        render_cards(data.get("crypto", []), category="crypto")
        st.markdown("</div>", unsafe_allow_html=True)

    # Chart + Summary column
    with col3:
        st.markdown(
            '<div class="section-title">📈 Advanced Chart</div>', unsafe_allow_html=True
        )
        with st.container():
            # Automatically pick the first stock as chart source
            chart_data = data.get("stocks") or data.get("crypto") or []
            if chart_data:
                chart_data[0]["symbol"]
                render_chart(chart_data, mode="stocks")
            else:
                st.warning("⚠️ No data available to render chart.")

            st.markdown(
                '<div class="section-title" style="margin-top:1rem;">🌐 Summary</div>',
                unsafe_allow_html=True,
            )
            render_summary()

        # 🛡️ Guardian footer
        st.markdown(
            '<div class="guardian-footer">🛡️ Astra Guardian V6 Active — Dashboard Secure ✅</div>',
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    st.write("🚀 Launching Astra Intelligence Dashboard…")
    render_dashboard()

    import streamlit as st


if __name__ == "__main__":
    st.set_page_config(
        page_title="Astra Intelligence Dashboard", layout="wide")

    # 🚫 Force-disable Streamlit dark overlay
    st.markdown(
        """
        <style>
        :root { color-scheme: light !important; }
        html, body, [data-testid="stAppViewContainer"], .stApp {
            background: radial-gradient(circle at 25% 25%, rgba(17,24,39,0.95), rgba(3,7,18,0.98)) !important;
            color: #E5E7EB !important;
        }
        [data-testid="stDecoration"], [data-testid="stStatusWidget"], [data-testid="stHeader"] {
            background: transparent !important;
        }
        </style>
    """,
        unsafe_allow_html=True,
    )

    # 🧠 Launch the Astra Intelligence Dashboard
    render_dashboard()
