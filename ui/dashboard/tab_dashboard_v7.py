from ui.dashboard.astra_bridge import AstraBridge
# -*- coding: utf-8 -*-
"""
Astra Intelligence - NeuralGlass Dashboard (v7)
-----------------------------------------------
Displays live intelligence data, grades, and predictions
with smooth layout and live updates.
"""

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
from engine.data_orchestrator import fetch_live_data
import json
from pathlib import Path



def render_dashboard():
    """Main dashboard layout"""
    st.header("📊 Astra Intelligence Dashboard")
    st.caption("Real-time predictions and confidence analytics powered by NeuralGlass.")

        # === Live Learning Metrics ===
    metrics_path = Path("state/learning_metrics.json")
    if metrics_path.exists():
        with open(metrics_path, "r") as f:
            metrics = json.load(f)
        st.subheader("🧠 Live Learning Metrics")
        st.metric("Cycle", metrics.get("cycle", 0))
        st.metric("Avg Reward", round(metrics.get("avg_reward", 0.0), 4))
        st.metric("Correlation Weight", round(metrics.get("correlation_weight", 0.0), 4))
        st.caption(f"Last Update: {metrics.get('timestamp', 'N/A')}")
    else:
        st.warning("No live metrics found. Run Learning Engine to generate data.")


    try:
        live_data = fetch_live_data()

        # Handle live data safely
        if not live_data or len(live_data) == 0:
            st.warning("⚠️ No live data available.")
            return

        # Convert to DataFrame depending on structure
        if isinstance(live_data, dict):
            df = pd.DataFrame([live_data])
        else:
            df = pd.DataFrame(live_data)

        required_cols = {"symbol", "grade", "confidence", "price", "timestamp"}
        missing = required_cols - set(df.columns)
        if missing:
            st.error(f"Missing columns in data: {missing}")
            return

        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")

        # Summary metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Assets Tracked", len(df))
        c2.metric("Avg Confidence", f"{df['confidence'].mean():.1f}%")
        c3.metric("A-Grade Picks", (df['grade'].str.startswith('A')).sum())
        st.divider()

        # Top performers
        st.subheader("🏆 Top Signals")
        top_df = df.sort_values("confidence", ascending=False).head(5)
        for _, row in top_df.iterrows():
            with st.container(border=True):
                st.write(f"**{row['symbol']}** — Grade {row['grade']}")
                st.write(f"Confidence: {row['confidence']:.1f}%")
                st.write(f"Price: ${row['price']:.2f}")
                st.caption(f"Updated: {row['timestamp']}")

        st.divider()

        # Charts
        st.subheader("📈 Confidence Distribution")
        st.plotly_chart(
            px.histogram(df, x="confidence", nbins=20, template="plotly_dark"),
            use_container_width=True
        )

        st.subheader("💹 Confidence Over Time")
        st.plotly_chart(
            px.line(
                df.sort_values("timestamp"),
                x="timestamp",
                y="confidence",
                color="grade",
                template="plotly_dark"
            ),
            use_container_width=True
        )

        # Footer
        st.caption(f"Last Updated: {df['timestamp'].max().strftime('%Y-%m-%d %H:%M:%S')}")

    except Exception as e:
        st.error(f"❌ Dashboard Error: {str(e)}")
        import traceback
        st.code(traceback.format_exc())


if __name__ == "__main__" or True:
    st.set_page_config(page_title="Astra Intelligence", layout="wide")
    render_dashboard()

# ------------------------------------------------------------------
# Astra Intelligence Live Data Feed (Phase-104 Integration)
bridge = AstraBridge()
data = bridge.collect(symbols=["AAPL", "TSLA"])
timestamp = data.get("timestamp", "N/A")
print(f"[AstraBridge] Live data fetched @ {timestamp}")

# ------------------------------------------------------------------
# Optional: Print structured persona output (debug mode)
for symbol, agents in data.items():
    if symbol == "timestamp":
        continue
    print(f"\\n🧩 {symbol} Persona Summary:")
    for agent_name, result in agents.items():
        print(f"  {agent_name}: {result}")

