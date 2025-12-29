import streamlit as st
import pandas as pd
from datetime import datetime

def render_predictions_tab():
    st.header("💡 Predictions Overview")
    st.caption("Displays current model predictions, signals, and confidence levels.")

    data = [
        {"Asset": "AAPL", "Signal": "BUY", "Confidence": 0.92, "Updated": datetime.now().strftime("%H:%M:%S")},
        {"Asset": "NVDA", "Signal": "BUY", "Confidence": 0.87, "Updated": datetime.now().strftime("%H:%M:%S")},
        {"Asset": "BTC-USD", "Signal": "HOLD", "Confidence": 0.63, "Updated": datetime.now().strftime("%H:%M:%S")},
        {"Asset": "TSLA", "Signal": "SELL", "Confidence": 0.71, "Updated": datetime.now().strftime("%H:%M:%S")},
    ]
    df = pd.DataFrame(data)
    st.dataframe(df, use_container_width=True)
