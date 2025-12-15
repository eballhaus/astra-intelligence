
# ============================================================
# 🧠 ASTRA INTELLIGENCE — Data Funnel System
# Selects top performing stocks & cryptos dynamically
# ============================================================

from astra_modules.engine.data_orchestrator import get_data
from universe.universe_builder import build_universe_optimized
from astra_modules.core.trade_mode import get_trade_mode
from astra_modules.guardian.guardian_v7 import guardian_log
from universe.universe_builder import build_universe_optimized
from astra_modules.core.trade_mode import get_trade_mode

def select_top_assets(category="stock", symbols=None, n=6):
    guardian_log(f"[DataFunnel] Selecting top {n} {category}s")
    if not symbols:
        symbols = get_symbols_for_category(category)
        symbols = ["AAPL","NVDA","MSFT","AMZN","TSLA","META","GOOGL"] if category=="stock" else ["BTC","ETH","SOL","BNB","ADA","AVAX","XRP"]

    scores = []
    for s in symbols:
        try:
            data = get_data(s, asset_type="crypto" if category!="stock" else "stock")
            if isinstance(data, dict):
                price = float(data.get("price", 0) or 0)
                change = float(data.get("change", 0) or 0)
                score = (abs(change) + (price / 1000))  # simplified for now
                scores.append((s, round(score, 3)))
        except Exception as e:
            guardian_log(f"[DataFunnel] ⚠️ Failed for {s}: {e}")

    top = sorted(scores, key=lambda x: x[1], reverse=True)[:n]
    guardian_log(f"[DataFunnel] Top {category}s: {top}")
    return top

# ============================================================
# 🔁 ASTRA UNIVERSE INTEGRATION — Auto-load stock & crypto sets
# ============================================================

def get_symbols_for_category(category: str):
    """Pull symbols dynamically from Astra’s unified universe builder."""
    mode = get_trade_mode()
    universe = build_universe_optimized()
    if category == "stock":
        symbols = universe.get("stocks", [])
    else:
        symbols = universe.get("crypto", [])
    guardian_log(f"[DataFunnel] Mode={mode} | Loaded {len(symbols)} {category} symbols from UniverseBuilder.")
    return symbols
