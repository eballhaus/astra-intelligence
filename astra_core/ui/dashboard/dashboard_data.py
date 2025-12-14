import pandas as pd
from astra_core.fetch_core import fetch_unified
from astra_core.guardian.guardian_v6 import guardian_log

guardian = guardian_log("🧠 [DashboardData] Astra unified data fetcher online.")


def load_data(selected_tab):
    """Load data for the given dashboard tab using Astra’s advanced fetch_unified."""
    guardian.log(f"[DashboardData] Fetching data for tab: {selected_tab}")

    try:
        if selected_tab == "Overview":
            df = fetch_unified.get_market_overview()
        elif selected_tab == "Crypto":
            df = fetch_unified.get_crypto_overview()
        else:
            df = fetch_unified.get_symbol_data(selected_tab)

        guardian.log(f"[DashboardData] ✅ Data loaded successfully for {selected_tab}")
        return df

    except Exception as e:
        guardian.log(f"[DashboardData] ❌ Failed to load data for {selected_tab}: {e}")
        return pd.DataFrame()
