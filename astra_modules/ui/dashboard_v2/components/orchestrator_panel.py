import streamlit as st
import pandas as pd

def render_orchestrator_panel(data: dict):
    orchestrator = data.get("orchestrator_state", {})
    if not orchestrator:
        st.info("No orchestrator data available.")
        return

    st.subheader("Active Agents")
    agents = orchestrator.get("agents", [])
    if agents:
        df = pd.DataFrame(agents)
        st.dataframe(df, use_container_width=True)
    else:
        st.write("No active agents detected.")

    st.subheader("System Logs")
    logs = orchestrator.get("logs", [])
    for log in logs[-5:]:
        st.text(log)
