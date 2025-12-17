import streamlit as st
from ui.dashboard.dashboard_sidebar import render_sidebar
from ui.dashboard.dashboard_data import load_data
from ui.dashboard.dashboard_cards import render_symbol_card
from ui.dashboard.dashboard_chart import render_chart
from ui.dashboard.dashboard_summary import render_summary

def render_dashboard():
    st.title('🚀 Astra Intelligence — Hydra Dashboard v8')

    # --- Sidebar ---
    config = render_sidebar()
    symbol = config.get('symbol', 'SPX')

    # --- Load Data ---
    df_stocks, df_cryptos = load_data()

    if 'selected_symbol' not in st.session_state:
        st.session_state.selected_symbol = symbol

    # --- Two Column Layout (Stocks / Cryptos) ---
    st.markdown('---')
    col1, col2 = st.columns(2)

    with col1:
        st.subheader('🏦 Top Stocks')
        if df_stocks is not None and not df_stocks.empty:
            for _, row in df_stocks.head(6).iterrows():
                render_symbol_card(row)
        else:
            st.info('No stock data available.')

    with col2:
        st.subheader('💠 Top Cryptos')
        if df_cryptos is not None and not df_cryptos.empty:
            for _, row in df_cryptos.head(6).iterrows():
                render_symbol_card(row)
        else:
            st.info('No crypto data available.')

    # --- Unified Chart ---
    st.markdown('---')
    selected = st.session_state.selected_symbol
    st.subheader(f'📈 Astra Advanced Chart — {selected}')
    render_chart(selected)

    # --- Contextual Insights ---
    st.markdown('---')
    render_summary({'trend': 'Neutral', 'volatility': 'Moderate', 'confidence': 72})
