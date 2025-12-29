    try:
        live_data = fetch_live_data()

        if not live_data or len(live_data) == 0:
            st.warning("⚠️ No live data available.")
            return

        # Handle live data shape safely
        if isinstance(live_data, dict):
            # Single record — wrap it in a list
            df = pd.DataFrame([live_data])
        else:
            # Assume list of dicts or DataFrame
            df = pd.DataFrame(live_data)
