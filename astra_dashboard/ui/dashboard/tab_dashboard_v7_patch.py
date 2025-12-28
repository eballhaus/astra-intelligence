def patch_dashboard_data():
    """Safely fetch and prepare live data for the dashboard."""
    try:
        live_data = fetch_live_data()

        if not live_data or len(live_data) == 0:
            st.warning("⚠️ No live data available.")
            return

        # Handle live data shape safely
        if isinstance(live_data, dict):
            if not live_data or len(live_data) == 0:
                st.warning("⚠️ No live data available.")
                return
            df = pd.DataFrame([live_data])
        else:
            df = pd.DataFrame(live_data)

        # Continue normal processing here...
        return df

    except Exception as e:
        st.error(f"Data processing error: {e}")
        return None
