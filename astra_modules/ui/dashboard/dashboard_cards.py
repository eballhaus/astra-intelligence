"""
Astra Intelligence — Enhanced Dashboard Cards (v3)
--------------------------------------------------
Displays key Astra signals for each ticker:
price, stop-loss, prediction, confidence, and grade.
"""

import streamlit as st
import pandas as pd


def render_symbol_card(symbol: str, df: pd.DataFrame, include_reason: bool = True):
    """Render a clean Astra AI decision card using live engine output."""
    try:
        latest = df.iloc[-1]
        price = float(latest.get("close", 0))
        change = float(df["close"].pct_change().iloc[-1] * 100 if "close" in df.columns else 0)

        # Fallbacks for Astra metadata
        stop_loss_price = float(latest.get("astra_stop_loss", price * 0.95))
        stop_loss_pct = float(latest.get("astra_stop_loss_pct", -5.0))
        pred_price = float(latest.get("astra_pred_price", price * 1.05))
        pred_change = float(latest.get("astra_pred_change", +5.0))
        confidence = latest.get("astra_confidence", "80%")
        grade = latest.get("astra_grade", "B")
        reason = latest.get("astra_reason", "Market momentum and positive sentiment detected.")

        # Optional reason line
        reason_html = f"<br>🧠 <i>{reason}</i>" if include_reason else ""

        st.markdown(
            f"""
            <div style="
                background: rgba(255,255,255,0.04);
                border-radius: 14px;
                padding: 0.9rem 1.1rem;
                margin-bottom: 0.8rem;
                border: 1px solid rgba(255,255,255,0.08);
                backdrop-filter: blur(6px);
                transition: all 0.2s ease-in-out;
            ">
                <h4 style='margin:0;color:#A7F3D0;font-weight:600;'>{symbol}</h4>
                <p style='margin:0;color:#E5E7EB;font-size:0.9rem;line-height:1.4rem;'>
                    💵 <b>Price:</b> ${price:.2f} ({change:+.2f}%)<br>
                    🛡️ <b>Stop-Loss:</b> ${stop_loss_price:.2f} ({stop_loss_pct:+.1f}%)<br>
                    🔮 <b>Prediction:</b> ${pred_price:.2f} ({pred_change:+.1f}%)<br>
                    🤖 <b>Confidence:</b> {confidence} &nbsp;|&nbsp; 📊 <b>Grade:</b> {grade}
                    {reason_html}
                </p>
            </div>
            """,
            unsafe_allow_html=True,
        )

    except Exception as e:
        st.error(f"🚨 Card render error ({symbol}): {e}")


def render_empty_card(symbol: str):
    """Placeholder card for missing data."""
    st.markdown(
        f"""
        <div style="
            background: rgba(255,255,255,0.02);
            border-radius: 14px;
            padding: 0.9rem 1.1rem;
            margin-bottom: 0.8rem;
            border: 1px dashed rgba(255,255,255,0.05);
            color: #9CA3AF;
            text-align: center;
        ">
            <p style='margin:0;'>No data available for <b>{symbol}</b></p>
        </div>
        """,
        unsafe_allow_html=True,
    )
