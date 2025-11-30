"""
Astra Dashboard Data Loader — integrates Astra agents and engines
"""

import streamlit as st
import pandas as pd
from astra_modules.fetch_core.fetch_unified import fetch_unified
from astra_modules.engine.ranking_engine import RankingEngine
from astra_modules.forecast.forecast_engine import ForecastEngine
from astra_modules.learning.learning_engine import LearningEngine
from astra_modules.agents.psychology_agent import PsychologyAgent
from astra_modules.agents.risk_agent import RiskAgent
from astra_modules.guardian.guardian_v6 import GuardianV6

@st.cache_data(ttl=900)
def load_data(symbol: str) -> pd.DataFrame:
    """Unified Astra data load pipeline."""
    try:
        df = fetch_unified(symbol)
        guardian = GuardianV6()
        df = guardian.validate_dataframe(df, required_columns=["date", "close"])
        if df.empty:
            return df

        # --- Intelligence synthesis ---
        ranking = RankingEngine()
        forecast = ForecastEngine()
        learning = LearningEngine()
        psychology = PsychologyAgent()
        risk = RiskAgent()

        # Forecast prediction
        pred_price, pred_change, conf = forecast.predict(symbol, df)
        # Risk & stop-loss
        stop_loss_price, stop_loss_pct = risk.compute_stop(symbol, df)
        # Grade & confidence from ranking engine
        grade = ranking.get_grade(symbol, df)
        # Reasoning summary
        reason = psychology.get_reason(symbol, df)

        # Append Astra meta data to DataFrame tail row
        df["astra_pred_price"] = pred_price
        df["astra_pred_change"] = pred_change
        df["astra_confidence"] = conf
        df["astra_grade"] = grade
        df["astra_stop_loss"] = stop_loss_price
        df["astra_stop_loss_pct"] = stop_loss_pct
        df["astra_reason"] = reason

        return df

    except Exception as e:
        st.warning(f"⚠️ Astra load error ({symbol}): {e}")
        return pd.DataFrame()
