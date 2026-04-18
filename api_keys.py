"""
Astra Unified API Pool (v2025.12)
Manages all 9 verified API providers for stocks, crypto, and fundamentals.
"""

import os
from dotenv import load_dotenv
from random import choice

# Load .env variables
load_dotenv()

# ==========================================================
# === STOCK / ETF / FUNDAMENTAL APIs =======================
# ==========================================================
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
FMP_API_KEY = (
    os.getenv("FMP_API_KEY", "")
    or os.getenv("FINANCIALMODELINGPREP_API_KEY", "")
    or os.getenv("FINANCIAL_MODELING_PREP_API_KEY", "")
)
ALPACA_API_KEY = (
    os.getenv("ALPACA_API_KEY", "")
    or os.getenv("APCA_API_KEY_ID", "")
    or os.getenv("ALPACA_API_KEY_ID", "")
)
ALPACA_SECRET_KEY = (
    os.getenv("ALPACA_SECRET_KEY", "")
    or os.getenv("APCA_API_SECRET_KEY", "")
    or os.getenv("ALPACA_API_SECRET", "")
)
NASDAQ_API_KEY = os.getenv("NASDAQ_API_KEY", "")
DATAJOCKEY_API_KEY = os.getenv("DATAJOCKEY_API_KEY", "")
SIMFIN_API_KEY = os.getenv("SIMFIN_API_KEY", "")

# ==========================================================
# === CRYPTO / BLOCKCHAIN APIs =============================
# ==========================================================
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY", "")
FRED_API_KEY = (
    os.getenv("FRED_API_KEY", "")
    or os.getenv("FRED_KEY", "")
)

# ==========================================================
# === API POOLS (organized by category) ====================
# ==========================================================
API_POOLS = {
    "stocks": [
        ("FMP", FMP_API_KEY),
        ("ALPHAVANTAGE", ALPHAVANTAGE_API_KEY),
        ("TWELVEDATA", TWELVEDATA_API_KEY),
        ("FINNHUB", FINNHUB_API_KEY),
        ("EODHD", EODHD_API_KEY),
        ("POLYGON", POLYGON_API_KEY),
        ("ALPACA", ALPACA_API_KEY),
    ],
    "macro": [
        ("FRED", FRED_API_KEY),
    ],
    "fundamentals": [
        ("NASDAQ", NASDAQ_API_KEY),
        ("DATAJOCKEY", DATAJOCKEY_API_KEY),
        ("SIMFIN", SIMFIN_API_KEY),
    ],
    "crypto": [
        ("MORALIS", MORALIS_API_KEY),
    ],
}

# ==========================================================
# === Core API Access Functions ============================
# ==========================================================
def get_available_api(category="stocks"):
    """Return the first available API key in this category."""
    for name, key in API_POOLS.get(category, []):
        if key and not key.startswith("YOUR_"):
            return name, key
    raise RuntimeError(f"No available API keys found for {category}")


def get_random_api(category="stocks"):
    """Return a random available API key from this category."""
    valid = [(n, k) for n, k in API_POOLS.get(category, []) if k and not k.startswith("YOUR_")]
    if not valid:
        raise RuntimeError(f"No available API keys found for {category}")
    return choice(valid)

# ==========================================================
# === Optional Diagnostic Print ============================
# ==========================================================
if __name__ == "__main__":
    print("\n🔍 Astra API Pool Verification\n")
    for cat in API_POOLS.keys():
        try:
            name, key = get_available_api(cat)
            print(f"✅ {cat.upper()}: Using {name}")
        except Exception as e:
            print(f"⚠️ {cat.upper()}: {e}")
