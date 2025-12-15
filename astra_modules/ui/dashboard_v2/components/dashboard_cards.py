
# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Cards (v5.0)
--------------------------------------------
Fully agent-integrated AstraGlass cards.
"""


import pandas as pd
import streamlit as st

from astra_modules.guardian.guardian_v7 import Guardian

guardian = Guardian()

try:
    from astra_modules.agents.momentum_agent import MomentumAgent
    from astra_modules.agents.neural_agent import NeuralAgent
    from astra_modules.agents.risk_agent import RiskAgent
    from astra_modules.engine.ranking_engine import RankingEngine

    print("[Cards] ✅ Agents successfully imported.")
except Exception as e:
    print(f"[Cards] ⚠️ Failed to import agents: {e}")
    MomentumAgent = RiskAgent = NeuralAgent = RankingEngine = None


# ============================================================
# 💹 Symbol Intelligence Card
# ============================================================
def render_symbol_card(symbol: str, df: pd.DataFrame = None, active: bool = False):
    """Render an AstraGlass card with key agent data."""
    if st.session_state.get(f"rendered_{symbol}", False):
        return
    st.session_state[f"rendered_{symbol}"] = True

    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        render_empty_card()
        return

    latest = df.iloc[-1].fillna(0)
    price = float(latest.get("price", latest.get("close", 0.0)))
    open_price = float(latest.get("open", price))
    change = price - open_price
    pct = (change / open_price) * 100 if open_price else 0
    color = "#4ade80" if change > 0 else "#f87171" if change < 0 else "#9ca3af"
    arrow = "▲" if change > 0 else "▼" if change < 0 else "→"

    stop_loss = latest.get("stop_loss", price * 0.95)
    prediction = latest.get("prediction", price * 1.05)
    confidence = latest.get("confidence", 75)
    momentum = latest.get("momentum", 50)
    grade = latest.get("grade", "B")

    html = f"""
    <div style="
        border:1px solid rgba(255,255,255,0.1);
        border-radius:12px;
        background:rgba(255,255,255,0.04);
        padding:0.8rem 1rem;
        margin-bottom:0.6rem;
    ">
        <div style="font-weight:600;color:{color};">{symbol} &nbsp; {arrow} {pct:+.2f}%</div>
        <div style="font-size:1.15rem;color:#e5e7eb;">${price:,.2f}</div>
        <div style="font-size:0.8rem;opacity:0.85;color:#9ca3af;">
            🛑 Stop: ${stop_loss:,.2f} &nbsp;
            🎯 Pred: ${prediction:,.2f} &nbsp;
            🌟 {grade} &nbsp;
            ⚡ {momentum} &nbsp;
            🧠 {confidence:.1f}%
        </div>
    </div>
    """
    import streamlit.components.v1 as components

    components.html(html, height=150, scrolling=False)


# ============================================================
# 🧩 Empty Card Placeholder
# ============================================================
def render_empty_card():
    import streamlit as st

    st.markdown(
        """
        <div style="padding:1rem;text-align:center;border-radius:10px;
                    border:1px dashed rgba(255,255,255,0.2);
                    color:#9ca3af;background:rgba(255,255,255,0.03);">
            🧩 <b>No data available</b>
        </div>
        """,
        unsafe_allow_html=True,
    )


__all__ = ["render_symbol_card", "render_empty_card"]

# ============================================================
# 🛡️ Safe Guardian Logger Wrapper
# ============================================================
try:
    pass

    def safe_log(msg):
        try:
            safe_log(msg)
        except Exception:
            print(msg)

except Exception:

    def safe_log(msg):
        print(msg)
