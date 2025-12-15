# -------------------------------------------------------------------
# 🧠 Astra Quick Mode — Skip Guardian full audit in UI sessions
# -------------------------------------------------------------------
from core.api_client import AstraAPI
from astra_modules.ui.dashboard.dashboard_data import load_data
from astra_modules.ui.dashboard.dashboard_chart import render_chart
from astra_modules.ui.dashboard.dashboard_cards import render_symbol_card
from astra_modules.guardian.guardian_v7 import guardian_log
import streamlit as st
import plotly.graph_objects as go
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timezone
import types
import sys
import concurrent.futures
import os

os.environ.setdefault("ASTRA_UI_MODE", "1")

# -*- coding: utf-8 -*-
"""
Astra Intelligence — Dashboard Tab (v4.4 Final Guardian Safe)
---------------------------------------------------------------
Unified dashboard powered by Astra internal APIs.
"""

# -------------------------------------------------------------------
# ⚡ Quick Pandas Loader Patch (skip heavy IO backends)
# -------------------------------------------------------------------


if "pandas.io.api" not in sys.modules:
    fake = types.ModuleType("pandas.io.api")
    for m in [
        "pandas.io.excel", "pandas.io.feather_format", "pandas.io.orc",
        "pandas.io.sas", "pandas.io.gbq", "pandas.io.html",
        "pandas.io.parquet", "pandas.io.xml", "pandas.io.sql",
    ]:
        sys.modules[m] = fake
# -------------------------------------------------------------------
# ✅ Updated imports for new Astra project structure
# -------------------------------------------------------------------

try:
    from force_hotfix import nuke_and_patch
    nuke_and_patch()
    print("✅ [Dashboard] FORCE-HOTFIX applied successfully — live data mode active")
except Exception as e:
    print(f"⚠️ [Dashboard] Force-hotfix unavailable: {e}")
)

    from force_hotfix import nuke_and_patch

    nuke_and_patch()
    print("✅ [Dashboard] FORCE-HOTFIX applied successfully — live data mode active")
except Exception as e:
    print(f"⚠️ [Dashboard] Force-hotfix unavailable: {e}")

# -------------------------------------------------------------------
# Standard Imports (AFTER hotfix patch)
# -------------------------------------------------------------------


- ----------------------------------------------------------------
    Optional Summary Import
    - ----------------------------------------------------------------
    from astra_modules.ui.dashboard.summary_cards import render_summary
except ImportError:
    guardian_log(
        "[Dashboard] ⚠️ summary_cards missing, using fallback summary renderer."
    )

    def render_summary():
        st.info("ℹ️ Summary unavailable (summary_cards module not found).")


# -------------------------------------------------------------------
# ⚙️ Streamlit Page Config
# -------------------------------------------------------------------
st.set_page_config(
    page_title = "Astra Intelligence Dashboard",
    page_icon = "🧠",
    layout = "wide",
    initial_sidebar_state = "collapsed",
)

# -------------------------------------------------------------------
# 🎨 AstraGlass Theme
# -------------------------------------------------------------------
st.markdown(
    """
    <style>
    body, .stApp {
        background: linear-gradient(135deg, #0f1729 0%, #1e293b 100%) !important;
        color: #E5E7EB !important;
        font-family: 'Inter', 'Segoe UI', sans-serif !important;
    }
    .section-header {
        color: #A7F3D0;
        font-size: 1.4rem;
        font-weight: 700;
        margin: 2rem 0 1rem 0;
        padding-bottom: 0.75rem;
        border-bottom: 2px solid rgba(167,243,208,0.3);
    }
    .astra-box {
        background: rgba(30,41,59,0.8);
        border: 1px solid rgba(167,243,208,0.25);
        border-radius: 12px;
        padding: 1.25rem;
        backdrop-filter: blur(10px);
        transition: all 0.3s ease-in-out;
    }
    .astra-box:hover {
        border-color: rgba(167,243,208,0.5);
        background: rgba(30,41,59,0.95);
        box-shadow: 0 0 15px rgba(167,243,208,0.1);
    }
    footer, header, #MainMenu {visibility:hidden;}
    </style>
    """,
    unsafe_allow_html = True,
)

- ----------------------------------------------------------------
    Auto-refresh
    - ----------------------------------------------------------------
    from streamlit_autorefresh import st_autorefresh

    st_autorefresh(interval=60000, key="dashboard_refresh_v44")
    guardian_log("[Dashboard] ⏱️ Auto-refresh enabled (60s interval)")
except ImportError:
    guardian_log("[Dashboard] ⚠️ streamlit_autorefresh missing.")


# -------------------------------------------------------------------
# ⚙️ Helpers
# -------------------------------------------------------------------
@ st.cache_data(ttl=60)
def cached_load(symbols: tuple) -> Dict[str, Optional[pd.DataFrame]]:
    return load_symbols_parallel(list(symbols))


def load_symbols_parallel(
    symbols: List[str], max_workers: int = 4
) -> Dict[str, Optional[pd.DataFrame]]:
    results = {}

    def load_single(symbol: str):
            df = load_data(symbol)
            return symbol, df if df is not None else None
        except Exception as e:
            guardian_log(f"[Dashboard] ⚠️ Load failed for {symbol}: {e}")
            return symbol, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        for symbol, df in ex.map(load_single, symbols):
            results[symbol] = df
    return results


def sanitize_dataframe(
    df: Optional[pd.DataFrame], symbol: str
) -> Optional[pd.DataFrame]:
    """Ensure dataframe has minimum valid structure before rendering."""
        if df is None or df.empty:
            guardian_log(f"[Sanitize] ⚠️ {symbol} empty or None")
            return None
        required_cols = {"timestamp", "close"}
        if not required_cols.issubset(df.columns):
            guardian_log(f"[Sanitize] ⚠️ {symbol} missing required columns, repairing.")
            now = datetime.now(timezone.utc)
            last_close = df["close"].iloc[-1] if "close" in df.columns else 0
            last_open = df["open"].iloc[-1] if "open" in df.columns else last_close
            last_high = df["high"].iloc[-1] if "high" in df.columns else last_close
            last_low = df["low"].iloc[-1] if "low" in df.columns else last_close
            last_volume = df["volume"].iloc[-1] if "volume" in df.columns else 0
            df = pd.DataFrame(
                [
                    {
                        "timestamp": now,
                        "open": last_open,
                        "high": last_high,
                        "low": last_low,
                        "close": last_close,
                        "volume": last_volume,
                    }
                ]
            )
        return df
    except Exception as e:
        guardian_log(f"[Sanitize] 🚨 {symbol} sanitization failed: {e}")
        return None


# -------------------------------------------------------------------
# 🕓 Lazy-load AstraAPI (safe, cached once)
# -------------------------------------------------------------------
@st.cache_resource
def get_api():
    from core.api_client import AstraAPI
    return AstraAPI()

def detect_top_assets(category: str = "equity", limit: int = 6) -> List[str]:
    """Auto-detect top assets using recent % change from AstraAPI."""
        api = get_api()
        symbols = api.list_symbols(category=category)
        if not symbols:
            raise ValueError("No symbols returned by AstraAPI")

        perf_data = []
        for s in symbols:
            df = load_data(s)
            if df is not None and not df.empty:
                    open_ = df.iloc[0].get("close", 0)
                    close = df.iloc[-1].get("close", 0)
                    pct = ((close - open_) / open_) * 100 if open_ else 0
                    perf_data.append((s, pct))
                except Exception:
                    continue

        if not perf_data:
            raise ValueError("No performance data available")

        guardian_log(f"[Timing] ⏱️ Sorting {len(perf_data)} assets...")
        sorted_syms = sorted(perf_data, key=lambda x: x[1], reverse=True)
        top_syms = [s[0] for s in sorted_syms[:limit]]
        guardian_log(f"[Dashboard] 🧠 Top {category.title()}s: {top_syms}")
        guardian_log(f"[Timing] ✅ detect_top_assets done ({category}) in {time.time()-t0:.2f}s")
        return top_syms

    except Exception as e:
        guardian_log(f"[Dashboard] ⚠️ Asset detection fallback ({category}): {e}")
        return (
            ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA", "GOOGL"]
            if category == "equity"
            else ["BTC/USD", "ETH/USD", "SOL/USD", "ADA/USD", "XRP/USD", "DOGE/USD"]
        )


# -------------------------------------------------------------------
# 🧠 Header
# -------------------------------------------------------------------
def render_header():
    col1, col2, col3, col4 = st.columns([3, 1.2, 1.2, 1])
    with col1:
        st.markdown(
            """
            <h1 style='color:#A7F3D0;font-size:2.3rem;font-weight:800;margin-bottom:0;'>🧠 Astra Intelligence Dashboard</h1>
            <p style='color:#9CA3AF;'>Real-time market intelligence powered by Astra Neural Networks</p>
            """,
            unsafe_allow_html=True,
        )
    with col2:
        market_open = datetime.now(timezone.utc).hour in range(13, 21)
        st.markdown(
            f"<div class='astra-box' style='text-align:center;color:{'#10B981' if market_open else '#F59E0B'};'>"
            f"<b>{'📈 OPEN' if market_open else '📉 CLOSED'}</b><br>"
            f"<span style='color:#9CA3AF;font-size:0.8rem;'>Market</span></div>",
            unsafe_allow_html=True,
        )
    with col3:
        now_utc = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        st.markdown(
            f"<div class='astra-box' style='text-align:center;'><b>⏱️ {now_utc}</b><br><span style='color:#9CA3AF;font-size:0.8rem;'>Live Time</span></div>",
            unsafe_allow_html=True,
        )
    with col4:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()


# -------------------------------------------------------------------
# 📈 Equities
# -------------------------------------------------------------------
def render_equities_section():
    st.markdown(
        "<div class='section-header'>📈 Top Equities</div>", unsafe_allow_html=True
    )
    top_equities = detect_top_assets("equity", 6)
    data = cached_load(tuple(top_equities))
    cols = st.columns(3)
    for i, s in enumerate(top_equities):
        with cols[i % 3]:
            df = sanitize_dataframe(data.get(s), s)
            if df is not None and not df.empty:
                render_symbol_card(s, df, active=(i == 0))
            else:
                st.warning(f"⚠️ No valid data for {s}")


# -------------------------------------------------------------------
# 💹 Crypto
# -------------------------------------------------------------------
def render_crypto_section():
    st.markdown(
        "<div class='section-header'>💹 Top Cryptocurrencies</div>",
        unsafe_allow_html=True,
    )
    top_cryptos = detect_top_assets("crypto", 6)
    data = cached_load(tuple(top_cryptos))
    cols = st.columns(3)
    for i, s in enumerate(top_cryptos):
        with cols[i % 3]:
            df = sanitize_dataframe(data.get(s), s)
            if df is not None and not df.empty:
                render_symbol_card(s, df)
            else:
                st.warning(f"⚠️ No valid data for {s}")


# -------------------------------------------------------------------
# 📊 Market Overview
# -------------------------------------------------------------------
def render_market_overview_chart():
    st.markdown(
        "<div class='section-header'>📊 Market Overview</div>", unsafe_allow_html=True
    )
    syms = detect_top_assets("equity", 4) + detect_top_assets("crypto", 2)
    all_data = cached_load(tuple(syms))
    chart_data = []
    for s, df in all_data.items():
        if df is not None and not df.empty:
                open_ = df.iloc[0]["close"]
                close = df.iloc[-1]["close"]
                pct = ((close - open_) / open_) * 100
                chart_data.append({"symbol": s, "change": pct})
            except Exception:
                continue
    if not chart_data:
        st.info("ℹ️ Waiting for data...")
        return
    dfc = pd.DataFrame(chart_data)
    colors = ["#4ade80" if c >= 0 else "#f87171" for c in dfc["change"]]
    fig = go.Figure(
        [
            go.Bar(
                x=dfc["symbol"],
                y=dfc["change"],
                text=[f"{c:+.2f}%" for c in dfc["change"]],
                marker=dict(color=colors),
            )
        ]
    )
    fig.update_layout(
        height=400,
        paper_bgcolor="rgba(30,41,59,0.6)",
        plot_bgcolor="rgba(30,41,59,0.3)",
        font=dict(color="#E5E7EB"),
    )
    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


# -------------------------------------------------------------------
# 📉 Advanced Chart
# -------------------------------------------------------------------
def render_advanced_chart_section():
    st.markdown(
        "<div class='section-header'>📉 Advanced Chart</div>", unsafe_allow_html=True
    )

    # Sidebar Controls (for compatibility, not used directly)
    st.sidebar.markdown("### 🧩 Chart Indicators")
    st.sidebar.checkbox("📈 Moving Averages (MA20, MA50)", value=True)
    st.sidebar.checkbox("💪 RSI (Relative Strength Index)", value=False)
    st.sidebar.checkbox("📊 MACD", value=False)
    st.sidebar.checkbox("🎯 Bollinger Bands", value=False)
    st.sidebar.checkbox("🔊 Volume", value=True)

    # Choose Asset
    symbol = (
        st.sidebar.text_input("Symbol", value=detect_top_assets("equity", 1)[0])
        .upper()
        .strip()
    )

    # Load Data
    df = load_data(symbol)
    df = sanitize_dataframe(df, symbol)

    if df is None or df.empty:
        st.warning(f"⚠️ No data available for {symbol}")
        return

    st.markdown(f"### {symbol} — Technical View", unsafe_allow_html=True)

    # ✅ define fig before try, avoids NameError
    fig = None

        # ✅ Build chart (from dashboard_chart.py)
        fig = render_chart(symbol, df, height=900)

        # ✅ Display chart
        if fig is not None:
            st.plotly_chart(fig, use_container_width=True)
            guardian_log(f"[Dashboard] ✅ Rendered advanced chart for {symbol}")
        else:
            st.warning("⚠️ No chart returned from render_chart().")

    except Exception as e:
        import traceback

        st.error(f"❌ Chart failed: {e}")
        guardian_log(f"[Dashboard] ⚠️ Chart rendering error for {symbol}: {e}")
        print(traceback.format_exc())

    # ============================================================


# Asset Selection
# ============================================================

# Select trading symbol (you can adapt this logic)
symbol = (
    st.text_input(
        "Symbol",
        value="AAPL",  # default fallback if detection fails
        help="Enter a trading symbol (e.g., AAPL, BTC/USD, ETH/USD)",
    )
    .upper()
    .strip()
)


# ============================================================
# Load & Render Chart Section (Fixed & Clean)
# ============================================================

# Load Data
df = load_data(symbol)
df = sanitize_dataframe(df, symbol)

if df is not None and not df.empty:
    st.markdown(f"### {symbol} — Technical View", unsafe_allow_html=True)

    # ✅ Define fig before use (avoids NameError if render_chart fails)
    fig = None

        # Build chart from dashboard_chart.py
        fig = render_chart(symbol, df, height=900)

        # ✅ Display chart only once
        if fig is not None:
            st.plotly_chart(
                fig,
                width="stretch",  # replaces deprecated use_container_width
                config={
                    "displayModeBar": True,
                    "displaylogo": False,
                    "modeBarButtonsToAdd": ["drawline", "drawopenpath", "eraseshape"],
                    "scrollZoom": True,
                    "responsive": True,
                },
            )
            guardian_log(f"[Dashboard] ✅ Rendered advanced chart for {symbol}")
        else:
            st.warning("⚠️ No chart returned from render_chart().")

    except Exception as e:
        import traceback

        st.error(f"❌ Chart failed: {e}")
        guardian_log(f"[Dashboard] ⚠️ Chart rendering error for {symbol}: {e}")
        print(traceback.format_exc())

    # ============================================================
    # Optional Data Summary
    # ============================================================
    with st.expander("📊 Data Summary", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Current Price", f"${df['close'].iloc[-1]:.2f}")
        with col2:
            if len(df) > 1:
                change_pct = (
                    (df["close"].iloc[-1] - df["close"].iloc[-2]) / df["close"].iloc[-2]
                ) * 100
                st.metric("24h Change", f"{change_pct:+.2f}%")
        with col3:
            st.metric("Data Points", len(df))


# -------------------------------------------------------------------
# 🧭 Footer
# -------------------------------------------------------------------
def render_footer():
    now = datetime.now(timezone.utc)
    st.markdown(
        f"<div style='text-align:center;color:#9CA3AF;font-size:0.8rem;padding:2rem 0;'>"
        f"🛡️ Guardian Protected • Auto-refresh 60s • Last update: {now.strftime('%H:%M:%S UTC')}<br>"
        f"Astra Intelligence Dashboard v4.4 • {now.strftime('%Y-%m-%d')}</div>",
        unsafe_allow_html=True,
    )


# -------------------------------------------------------------------
# 🚀 MAIN
# -------------------------------------------------------------------
def main():
    guardian_log("[Dashboard] 🚀 Astra Dashboard v4.4 Live")
    render_header()
    render_equities_section()
    render_crypto_section()
    render_market_overview_chart()
    render_advanced_chart_section()
    render_summary()
    render_footer()
    guardian_log("[Dashboard] ✅ Dashboard Rendered Successfully")


-----------------------------------------------------------------
    BACKGROUND LEARNING CONTROL (UI INTEGRATION)
    -----------------------------------------------------------------
    import streamlit as st

# -------------------------------------------------------------------
# ⚡ Quick Pandas Loader Patch (skip heavy IO backends)
# -------------------------------------------------------------------
import sys
import types

if "pandas.io.api" not in sys.modules:
    fake = types.ModuleType("pandas.io.api")
    for m in [
        "pandas.io.excel", "pandas.io.feather_format", "pandas.io.orc",
        "pandas.io.sas", "pandas.io.gbq", "pandas.io.html",
        "pandas.io.parquet", "pandas.io.xml", "pandas.io.sql",
    ]:
        sys.modules[m] = fake

        # 🚀 Faster startup — disable automatic loop start for now
        # toggle_background_learning(on=True, interval_minutes=5)
        main()

        # 🧭 Manual background loop control (on-demand)
        st.divider()
        st.subheader("⚙️ Background Learning Control")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("▶️ Start Background Learning"):
                toggle_background_learning(on=True)
        with col2:
            if st.button("⏹ Stop Background Learning"):
                toggle_background_learning(on=False)

    except Exception as e:
        guardian_log(f"[Dashboard] 🚨 Fatal dashboard error: {e}")
        st.error("🚨 Dashboard failed to render. Check Astra logs.")

# -------------------------------------------------------------------
# 🧠 BACKGROUND LEARNING CONTROL (UI INTEGRATION — CLEAN FIX)
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# 🧠 BACKGROUND LEARNING CONTROL (FINAL CLEAN VERSION)
# -------------------------------------------------------------------
_background_loop = None  # keep global reference


def _lazy_import_background_loop():
    """Import BackgroundLoop only when needed (lazy load)."""
    from astra_modules.engine.background_loop import BackgroundLoop
    return BackgroundLoop


def toggle_background_learning(on: bool = True, interval_minutes: int = 10):
    """
    Start or stop the background learning loop (lazy import, safe).
    """
    import streamlit as st
    global _background_loop

    BackgroundLoop = _lazy_import_background_loop()

    if on:
        if _background_loop and getattr(_background_loop, "running", False):
            st.info("ℹ️ Background learning already running.")
            return
        _background_loop = BackgroundLoop(interval_minutes=interval_minutes)
        _background_loop.start()
        st.success(f"✅ Background learning started (interval: {interval_minutes} min)")
    else:
        if _background_loop:
            _background_loop.stop()
            st.warning("⏹ Background learning stopped.")
        else:
            st.info("ℹ️ No background learning loop active.")
