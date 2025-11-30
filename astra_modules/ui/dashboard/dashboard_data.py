"""
Astra Intelligence - Dashboard Data Layer
-----------------------------------------
Centralized data fetch and orchestration for the Astra Dashboard.
Integrates:
• Unified market data (stocks, crypto, ETFs)
• Cached Astra forecasts (via forecast_engine)
• Smart error handling and caching
• Streamlit-safe performance (10 min TTL)
"""

import streamlit as st
from datetime import datetime
from astra_modules.fetch_core.fetch_unified import fetch_unified
from astra_modules.forecast.forecast_engine import get_forecast
from astra_modules.engine.ranking_engine import RankingEngine

@st.cache_data(ttl=600, show_spinner=False)
def load_dashboard_data(symbols: list[str] = None, include_forecast: bool = True):
    """
    Loads and returns a unified data bundle for dashboard display.
    Includes OHLCV market data, Astra AI forecasts, and rank scores.
    """

    data_results = {}

    if not symbols:
        return {}

    for symbol in symbols:
        try:
            # 1️⃣ Fetch real market data
            unified = fetch_unified(symbol)
            df = unified.get("df")
            if df is None or df.empty:
                st.warning(f"No OHLCV data available for {symbol}.")
                continue

            # 2️⃣ Initialize data bundle
            data_bundle = {
                "symbol": symbol,
                "df": df,
                "timestamp": datetime.utcnow().isoformat(),
                "forecast": None,
                "rank_score": None,
                "volatility": unified.get("volatility"),
                "sparkline": unified.get("sparkline"),
            }

            # 3️⃣ Compute ranking score (optional, if agents are active)
            try:
                rank_engine = RankingEngine()
                ranked = rank_engine.rank([symbol])
                if ranked and isinstance(ranked, list):
                    data_bundle["rank_score"] = ranked[0].get("rank_score")
            except Exception as rank_err:
                print(f"[WARN] RankingEngine unavailable for {symbol}: {rank_err}")

            # 4️⃣ Fetch forecast (AI or cached)
            if include_forecast:
                try:
                    forecast_data = get_forecast(symbol)
                    if forecast_data:
                        data_bundle["forecast"] = forecast_data
                except Exception as forecast_err:
                    print(f"[WARN] Forecast unavailable for {symbol}: {forecast_err}")

            # 5️⃣ Store symbol bundle
            data_results[symbol] = data_bundle

        except Exception as e:
            print(f"[ERROR] Failed to load data for {symbol}: {e}")

    return data_results
