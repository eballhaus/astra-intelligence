"""
Astra Unified API Pool (v2025.12)
Manages all 9 verified API providers for stocks, crypto, and fundamentals.
"""

import os
from dotenv import load_dotenv
from random import choice

# Load .env variables
load_dotenv()


def _first_env(*names):
    """Resolve the first non-empty env var from a list of accepted aliases."""
    for name in names:
        value = str(os.getenv(name, "") or "").strip()
        if value:
            return value
    return ""


def _sync_canonical_env(canonical_name, *aliases):
    """Backfill a canonical env var from accepted aliases without hardcoding secrets."""
    current = str(os.getenv(canonical_name, "") or "").strip()
    if current:
        return current
    value = _first_env(*aliases)
    if value:
        os.environ[canonical_name] = value
        return value
    return ""

# ==========================================================
# === STOCK / ETF / FUNDAMENTAL APIs =======================
# ==========================================================
ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY", "")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY", "")
EODHD_API_KEY = os.getenv("EODHD_API_KEY", "")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "")
FMP_API_KEY = _sync_canonical_env(
    "FMP_API_KEY",
    "FINANCIALMODELINGPREP_API_KEY",
    "FINANCIAL_MODELING_PREP_API_KEY",
    "FMP_KEY",
    "FMP_TOKEN",
    "FMP_API",
    "FINANCIAL_MODELING_PREP_KEY",
)
NASDAQ_API_KEY = os.getenv("NASDAQ_API_KEY", "")
DATAJOCKEY_API_KEY = os.getenv("DATAJOCKEY_API_KEY", "")
SIMFIN_API_KEY = os.getenv("SIMFIN_API_KEY", "")

# ==========================================================
# === CRYPTO / BLOCKCHAIN APIs =============================
# ==========================================================
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY", "")

# ==========================================================
# === API POOLS (organized by category) ====================
# ==========================================================
API_POOLS = {
    "stocks": [
        ("ALPHAVANTAGE", ALPHAVANTAGE_API_KEY),
        ("TWELVEDATA", TWELVEDATA_API_KEY),
        ("FINNHUB", FINNHUB_API_KEY),
        ("EODHD", EODHD_API_KEY),
        ("POLYGON", POLYGON_API_KEY),
        ("FMP", FMP_API_KEY),
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
    valid = [(n, k) for n, k in API_POOLS.get(category, []) if k and not key.startswith("YOUR_")]
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
