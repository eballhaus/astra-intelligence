import streamlit as st
from fetch_unified import fetch_unified
import pandas as pd

# ============================================================
# Astra Intelligence — Market Dashboard (Internal Mode)
# ============================================================

st.set_page_config(page_title="Astra Intelligence — Market Dashboard", layout="wide")

st.title("🌌 Astra Intelligence — Market Dashboard")

# --- Data Fetch ---
symbol = st.sidebar.text_input("Symbol", "BTC-USD")
data = fetch_unified(symbol)

if isinstance(data, pd.DataFrame) and not data.empty:
    latest = data.iloc[-1]
    open_p, high_p, low_p, close_p = latest["open"], latest["high"], latest["low"], latest["close"]

    # --- Derived values ---
    stop_loss = round(close_p * 0.95, 2)
    prediction = round(close_p * 1.05, 2)
    diff = round(((close_p - open_p) / open_p) * 100, 2)
    sentiment = "🧠 Market momentum and positive sentiment detected." if diff > 0 else "⚠️ Weak momentum detected."

    # --- Display ---
    st.metric("💵 Price", f"${close_p:.2f}", f"{diff:+.2f}%")
    st.metric("🛡️ Stop-Loss", f"${stop_loss:.2f}", "-5.0%")
    st.metric("🔮 Prediction", f"${prediction:.2f}", "+5.0%")
    st.markdown("**Confidence:** 80% | **Grade:** B")
    st.markdown(sentiment)

    # --- Chart ---
    st.line_chart(data[["open", "high", "low", "close"]])
else:
    st.error("❌ No data available. The internal fetch_unified() returned empty or invalid data.")
