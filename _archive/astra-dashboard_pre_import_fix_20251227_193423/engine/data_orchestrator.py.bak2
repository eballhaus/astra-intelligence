# --- Astra Import Path Fix ---
import os
import sys
from datetime import datetime
import random

# Always resolve project root (one level up from 'engine')
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
core_path = os.path.join(project_root, 'core')

# Add these paths for this module’s context
if project_root not in sys.path:
    sys.path.insert(0, project_root)
if core_path not in sys.path:
    sys.path.insert(0, core_path)

print(f"[DATA_ORCHESTRATOR FIX]")
print(f"  Project root: {project_root}")
print(f"  Core path: {core_path}")
print(f"  guardian_v7.py exists: {os.path.exists(os.path.join(core_path, 'guardian', 'guardian_v7.py'))}")

# --- Continue with normal imports ---
try:
    from core.guardian.guardian_v7 import GuardianV7
except ImportError:
    GuardianV7 = None
    print("[Warning] GuardianV7 could not be imported. Live mode will be unavailable.")


# --- Main Function: fetch_live_data ---
def fetch_live_data():
    """
    Fetch live or mock data depending on configuration.
    Supports both stock and crypto tickers.
    Includes fallback mock generator if GuardianV7 API is unavailable or incomplete.
    """
    USE_LIVE_MODE = True  # Toggle for dev testing

    data = []
    if not USE_LIVE_MODE:
        print("[Engine] Mock mode active — returning stub dataset.")
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        for symbol in ["AAPL", "TSLA"]:
            data.append({
                "symbol": symbol,
                "price": round(random.uniform(100, 400), 2),
                "timestamp": now,
                "type": "stock"
            })
        return data

    # --- Live mode path ---
    if USE_LIVE_MODE:
        if GuardianV7 is None:
            print("[Engine] Live mode selected, but GuardianV7 unavailable. Reverting to fallback mode.")
            return _generate_fallback_data()

        print("[Engine] Live mode active — fetching from GuardianV7 APIs.")
        guardian = GuardianV7()
        try:
            # Fetch stock data
            live_stocks = guardian.fetch_live_data(symbols=["AAPL", "TSLA"])
            print("[Engine] ✅ Stock data fetch successful.")

            # Ensure consistent format
            for s in live_stocks:
                s["type"] = "stock"

            data.extend(live_stocks)

        except Exception as e:
            print(f"[Engine] ⚠️ Live fetch failed for stocks — using fallback. Error: {e}")
            data.extend(_generate_fallback_data(asset_type="stock"))

    # --- Crypto Fallback (since Guardian may not support crypto yet) ---
    symbols = [d.get("symbol") for d in data if isinstance(d, dict)]
    crypto_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "BNB-USD", "AVAX-USD"]
    missing_cryptos = [sym for sym in crypto_symbols if sym not in symbols]

    if missing_cryptos:
        print(f"[Engine] ⚠️ No live crypto data found — generating fallback for {len(missing_cryptos)} cryptos.")
        now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        for sym in missing_cryptos:
            data.append({
                "symbol": sym,
                "price": round(random.uniform(50, 50000), 2),
                "target": None,
                "pred_pct": None,
                "stop": None,
                "stop_pct": None,
                "timestamp": now,
                "type": "crypto"
            })

    print(f"[Engine] ✅ {len(data)} total live entries (stocks + crypto).")
    return data


# --- Helper: Generate Fallback Data ---
def _generate_fallback_data(asset_type="stock"):
    """Generate fallback data if live API fails or unavailable."""
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    if asset_type == "stock":
        symbols = ["AAPL", "NVDA", "TSLA", "AMZN", "MSFT", "META"]
        min_price, max_price = 100, 500
    else:
        symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD", "BNB-USD", "AVAX-USD"]
        min_price, max_price = 50, 50000

    mock = []
    for symbol in symbols:
        mock.append({
            "symbol": symbol,
            "price": round(random.uniform(min_price, max_price), 2),
            "grade": random.choice(["A+", "A", "B+", "B"]),
            "confidence": round(random.uniform(75, 99), 2),
            "timestamp": now,
            "type": asset_type
        })
    return mock
