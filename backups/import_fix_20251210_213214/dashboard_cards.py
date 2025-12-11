# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Cards (v3.3 LiveFix)
-------------------------------------------------
Displays AstraGlass cards with live Astra data, predictive continuity,
and Astra Intelligence grade/confidence simulation.

✅ Fully live-mode aware
✅ Respects ASTRA_LIVE_MODE toggle
✅ Freshness revalidation (5-minute rule)
✅ Guardian-integrated logging
✅ Timestamp normalization (UTC-aware)
✅ Source propagation after live refresh
✅ Optional Streamlit live rerun for real-time update
"""

import os
import sys
from datetime import datetime, timezone
from typing import Optional, Tuple

import pandas as pd
import streamlit as st

from astra_core.core.api_client import AstraAPI
from astra_core.guardian.guardian_v6 import guardian


# ===================================================================
# 🧩 Safe Print Helper
# ===================================================================
def safe_print(*args, **kwargs) -> None:
    try:
        print(*args, **kwargs)
    except OSError:
        try:
            sys.stderr.write(" ".join(map(str, args)) + "\n")
        except Exception:
            pass


# ===================================================================
# 📊 Data Extraction Utilities
# ===================================================================
def extract_price(df: pd.DataFrame) -> Optional[float]:
    try:
        if df is None or df.empty:
            return None
        for col in ["close", "price", "last"]:
            if col in df.columns:
                val = df[col].iloc[-1]
                if pd.notna(val):
                    return float(val)
    except Exception as e:
        guardian.log(f"[DashboardCards] ⚠️ Price extraction error: {e}")
    return None


def extract_change(df: pd.DataFrame) -> Optional[float]:
    try:
        if df is None or df.empty:
            return None
        if "percentchange" in df.columns:
            val = df["percentchange"].iloc[-1]
            if pd.notna(val):
                return float(val)
        if "change" in df.columns and "close" in df.columns:
            close = df["close"].iloc[-1]
            ch = df["change"].iloc[-1]
            if pd.notna(close) and pd.notna(ch) and close != 0:
                return (ch / close) * 100
        if "open" in df.columns and "close" in df.columns:
            open_price = df["open"].iloc[-1]
            close_price = df["close"].iloc[-1]
            if pd.notna(open_price) and open_price != 0:
                return ((close_price - open_price) / open_price) * 100
        if "close" in df.columns and len(df) > 1:
            prev = df["close"].iloc[-2]
            curr = df["close"].iloc[-1]
            if pd.notna(prev) and prev != 0:
                return ((curr - prev) / prev) * 100
    except Exception as e:
        guardian.log(f"[DashboardCards] ⚠️ Change extraction error: {e}")
    return None


# ===================================================================
# 🧠 Astra Intelligence Grade Simulator
# ===================================================================
def simulate_astra_grade_and_confidence(df: pd.DataFrame) -> Tuple[str, float]:
    try:
        if df is None or df.empty or "close" not in df.columns:
            return ("NEUTRAL", 0.0)
        closes = df["close"].astype(float)
        returns = closes.pct_change().dropna()
        if len(returns) == 0:
            return ("NEUTRAL", 0.0)
        mean_change = returns.mean() * 100
        vol = returns.std() * 100
        if mean_change > 0.8 and vol < 1.5:
            grade = "STRONG BUY"
        elif mean_change > 0.3:
            grade = "BUY"
        elif mean_change < -0.8 and vol < 1.5:
            grade = "STRONG SELL"
        elif mean_change < -0.3:
            grade = "SELL"
        else:
            grade = "HOLD"
        confidence = max(20.0, 100.0 - min(vol * 8.0, 80.0))
        return (grade, round(confidence, 1))
    except Exception as e:
        guardian.log(f"[DashboardCards] ⚠️ Grade simulation error: {e}")
        return ("NEUTRAL", 0.0)


def get_grade_color(grade: str) -> str:
    g = grade.upper()
    if "STRONG BUY" in g:
        return "#10B981"
    if "BUY" in g:
        return "#34D399"
    if "STRONG SELL" in g:
        return "#EF4444"
    if "SELL" in g:
        return "#F87171"
    if "HOLD" in g:
        return "#FBBF24"
    return "#6B7280"


# ===================================================================
# 🎯 Target & Stop Loss Helpers
# ===================================================================
def calc_target(price: float, pct: float = 5.0) -> float:
    try:
        if price and price > 0:
            return round(price * (1 + pct / 100), 2)
    except Exception:
        pass
    return 0.0


def calc_stop(price: float, pct: float = -3.0) -> float:
    try:
        if price and price > 0:
            stop = price * (1 + pct / 100)
            return round(max(stop, 0.01), 2)
    except Exception:
        pass
    return 0.0


# ===================================================================
# 🧭 Source and Freshness Info
# ===================================================================
def get_source_info(df: pd.DataFrame) -> str:
    try:
        if df is None or df.empty:
            return "❓ no data"
        src = df.attrs.get("source", "unknown")
        ts = df.attrs.get("timestamp")
        if ts is None:
            return f"❓ {src} | ⚠️ unknown"
        try:
            if isinstance(ts, str):
                ts = pd.Timestamp(ts).tz_localize(None)
            age_mins = (datetime.utcnow() - ts).total_seconds() / 60.0
        except Exception:
            age_mins = None
        fresh = "✅ Fresh" if age_mins and age_mins < 5 else "⚠️ Stale"
        icon_map = {
            "live": "📡",
            "astra_api": "📡",
            "astra_api_live": "📡",
            "backend": "⚡",
            "astra_forecast": "🔮",
            "forecast": "🔮",
            "cache": "💾",
            "refetch": "🔄",
            "synthetic": "🧩",
            "mock": "🧩",
            "unified_fetch": "⚡",
        }
        icon = icon_map.get(src, "❓")
        return f"{icon} {src} | {fresh}"
    except Exception as e:
        guardian.log(f"[DashboardCards] ⚠️ Source info error: {e}")
        return "❓ unknown | ⚠️ error"


# ===================================================================
# 🔄 Improved Freshness Check (UTC-aware)
# ===================================================================
def check_data_freshness_with_age(df: pd.DataFrame, symbol: str) -> Tuple[bool, float]:
    """Check data freshness and return age in seconds."""
    try:
        if df is None or df.empty or "timestamp" not in df.columns:
            guardian.log(f"[DashboardCards] ⚠️ {symbol}: No timestamp column")
            return (False, 999999)

        # Normalize timestamp dtype
        df["timestamp"] = pd.to_datetime(
            df["timestamp"], utc=True, errors="coerce")
        last_timestamp = df["timestamp"].max()
        if pd.isna(last_timestamp):
            return (False, 999999)

        now = datetime.now(timezone.utc)
        age_seconds = (now - last_timestamp).total_seconds()
        is_fresh = age_seconds <= 300

        guardian.log(
            f"[DashboardCards] ⏱️ {symbol}: age={age_seconds:.1f}s, fresh={is_fresh}"
        )
        return (is_fresh, age_seconds)

    except Exception as e:
        guardian.log(
            f"[DashboardCards] ⚠️ Freshness check error for {symbol}: {e}")
        return (False, 999999)


# ===================================================================
# 💳 Main Card Renderer (Enhanced Live Mode)
# ===================================================================
def render_symbol_card(
    symbol: str, df: Optional[pd.DataFrame], active: bool = False
) -> None:
    try:
        guardian.log(f"[DashboardCards] 🔍 Starting render for {symbol}")

        if df is None or df.empty:
            guardian.log(f"[DashboardCards] ⚠️ No data for {symbol}")
            st.warning(f"{symbol}: ⚠️ No data available")
            return

        # Check structure
        required_cols = ["close", "timestamp"]
        for col in required_cols:
            if col not in df.columns:
                df[col] = datetime.utcnow() if col == "timestamp" else 100.0

        # Check freshness
        is_fresh, age_seconds = check_data_freshness_with_age(df, symbol)
        live_mode = os.getenv("ASTRA_LIVE_MODE", "true").lower() == "true"

        # Attempt live refresh if stale
        if not is_fresh and live_mode:
            guardian.log(
                f"[DashboardCards] 🔄 Data stale for {symbol} ({age_seconds:.1f}s). Attempting live refresh..."
            )
            try:
                api = AstraAPI()
                df_fresh = api.get_market_data(symbol)
                if df_fresh is not None and not df_fresh.empty:
                    guardian.log(
                        f"[DashboardCards] ✅ Live refresh succeeded for {symbol}"
                    )
                    df = df_fresh
                    df["timestamp"] = pd.to_datetime(
                        df["timestamp"], utc=True, errors="coerce"
                    )
                    df.attrs["source"] = "astra_api_live"
                    df.attrs["timestamp"] = datetime.utcnow()
                    is_fresh, age_seconds = check_data_freshness_with_age(
                        df, symbol)
                    st.experimental_rerun()
                else:
                    guardian.log(
                        f"[DashboardCards] ⚠️ Live refresh returned empty for {symbol}"
                    )
            except Exception as e:
                guardian.log(
                    f"[DashboardCards] ⚠️ Live refresh failed for {symbol}: {e}"
                )

        # Extract data
        price = extract_price(df)
        change = extract_change(df)
        grade, confidence = simulate_astra_grade_and_confidence(df)
        target = calc_target(price if price else 0)
        stop = calc_stop(price if price else 0)
        source_info = get_source_info(df)

        # Timestamp display
        asof = df.attrs.get("timestamp") or df["timestamp"].max()
        if isinstance(asof, str):
            asof = pd.Timestamp(asof)
        asof_str = (
            asof.strftime("%Y-%m-%d %H:%M:%S UTC")
            if isinstance(asof, (datetime, pd.Timestamp))
            else "unknown"
        )

        # Colors & display
        price_color = "#4ade80" if (change or 0) >= 0 else "#f87171"
        grade_color = get_grade_color(grade)
        border_color = "#A7F3D0" if active else "rgba(255,255,255,0.1)"
        display_price = price if price is not None else 0.0
        display_change = change if change is not None else 0.0

        st.markdown(
            f"""
            <div style='background:rgba(255,255,255,0.03);border-radius:10px;
            border:2px solid {border_color};padding:1rem;text-align:left;min-height:240px;'>
            <div style='display:flex;justify-content:space-between;'>
                <b style='color:#A7F3D0;font-size:1.1em;'>{symbol}</b>
                <span style='color:{price_color};font-weight:bold;font-size:0.95em;'>{display_change:+.2f}%</span>
            </div>
            <div style='margin:0.75rem 0;'>
                <span style='color:{price_color};font-size:1.4em;font-weight:bold;'>${display_price:.2f}</span>
            </div>
            <div style='font-size:0.85em;color:#E5E7EB;'>
                🎯 Target: <b style='color:#14B8A6;'>${target:.2f}</b><br>
                🛑 Stop: <b style='color:#f87171;'>${stop:.2f}</b>
            </div>
            <div style='margin-top:0.75rem;padding:0.5rem;background:rgba(255,255,255,0.05);
            border-left:3px solid {grade_color};border-radius:6px;'>
                🧠 <b style='color:{grade_color};'>{grade}</b><br>
                <span style='font-size:0.8em;color:#9CA3AF;'>Confidence: {confidence:.1f}%</span>
            </div>
            <div style='font-size:0.75em;color:#6B7280;margin-top:0.5rem;'>
                {source_info}<br>🕒 {asof_str}
            </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        guardian.log(
            f"[DashboardCards] ✅ Rendered {symbol}: ${display_price:.2f}, {display_change:+.2f}%, {grade} ({confidence:.1f}%)"
        )

    except Exception as e:
        guardian.log(f"[DashboardCards] 🚨 Render error for {symbol}: {e}")
        st.error(f"⚠️ Render failed for {symbol}")


# ===================================================================
# 🧪 Test Function
# ===================================================================
def test_render():
    """Test the render function with sample data."""
    from datetime import timedelta

    now = datetime.utcnow()
    test_data = pd.DataFrame(
        {
            "timestamp": [now - timedelta(minutes=2), now - timedelta(minutes=1)],
            "open": [100.0, 101.0],
            "high": [102.0, 103.0],
            "low": [99.0, 100.0],
            "close": [101.0, 102.0],
            "volume": [1000, 1200],
        }
    )
    test_data.attrs = {"source": "test"}
    render_symbol_card("TEST", test_data)
