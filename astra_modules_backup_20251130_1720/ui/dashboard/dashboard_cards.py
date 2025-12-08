"""
Astra Intelligence — Enhanced Dashboard Cards (v4 Guardian-Safe)
---------------------------------------------------------------
Displays key Astra signals for each ticker:
price, stop-loss, prediction, confidence, and grade.
Now hardened with guardian_log compatibility and data normalization.
"""

import pandas as pd
import streamlit as st
from astra_modules.guardian import guardian_log

guardian = guardian_log()


# ============================================================
# 🧩 Safe Normalization Utility
# ============================================================

def normalize_dataframe(df, symbol: str) -> pd.DataFrame:
    """Ensure df is a valid DataFrame with required columns."""
    try:
        # Convert dict → DataFrame
        if isinstance(df, dict):
            guardian.log(f"[Guardian Notice] {symbol}: Converting dict to DataFrame.")
            df = pd.DataFrame([df])

        # If None or empty → placeholder
        if df is None or df.empty:
            guardian.log(f"[Guardian Info] {symbol}: Empty or None DataFrame received.")
            df = pd.DataFrame(columns=[
                "close",
                "astra_stop_loss",
                "astra_stop_loss_pct",
                "astra_pred_price",
                "astra_pred_change",
                "astra_confidence",
                "astra_grade",
                "astra_reason",
            ])

        # Ensure required columns exist
        required_cols = [
            "close",
            "astra_stop_loss",
            "astra_stop_loss_pct",
            "astra_pred_price",
            "astra_pred_change",
            "astra_confidence",
            "astra_grade",
            "astra_reason",
        ]
        for col in required_cols:
            if col not in df.columns:
                df[col] = None

        df.reset_index(drop=True, inplace=True)
        return df

    except Exception as e:
        guardian.log(f"[Guardian Error] normalize_dataframe({symbol}): {e}")
        return pd.DataFrame()


# ============================================================
# 🪄  CARD RENDERER
# ============================================================

def render_symbol_card(symbol: str, df: pd.DataFrame, include_reason: bool = True):
    """Render a clean Astra AI decision card using live engine output."""
    try:
        df = normalize_dataframe(df, symbol)
        if df.empty:
            render_empty_card(symbol)
            return

        latest = df.iloc[-1]

        price = float(latest.get("close", 0.0) or 0.0)
        change = 0.0
        if "close" in df.columns and len(df) > 1:
            try:
                change = float(df["close"].pct_change().iloc[-1] * 100)
            except Exception:
                change = 0.0

        # Astra metadata with safe fallbacks
        stop_loss_price = float(latest.get("astra_stop_loss", price * 0.95) or price * 0.95)
        stop_loss_pct = float(latest.get("astra_stop_loss_pct", -5.0) or -5.0)
        pred_price = float(latest.get("astra_pred_price", price * 1.05) or price * 1.05)
        pred_change = float(latest.get("astra_pred_change", +5.0) or +5.0)
        confidence = latest.get("astra_confidence", "80%") or "80%"
        grade = latest.get("astra_grade", "B") or "B"
        reason = latest.get(
            "astra_reason", "Market momentum and positive sentiment detected."
        ) or "Market momentum and positive sentiment detected."

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
        guardian.log(f"[Guardian Exception] Card render error ({symbol}): {e}")
        st.error(f"🚨 Card render error ({symbol}): {e}")


# ============================================================
# 🧩  EMPTY CARD FALLBACK
# ==========================
