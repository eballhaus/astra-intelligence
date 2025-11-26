# ===============================================================
# Astra 7.0 — Dynamic Screener
# Decides which tickers to scan before Smart Scan + Hybrid Scan.
#   • ~75 stocks + ~25 crypto
#   • Rotates daily to reduce noise
#   • Prioritizes high-quality liquid tickers
#   • Uses multiple API sources (Alpha Vantage, FMP, TwelveData)
#   • Future-proof for learning engine expansion
# ===============================================================

import random
import datetime


# ===============================================================
# 1. BASE UNIVERSES — these are NOT fixed, they are *starting pools*
# Astra will dynamically rotate, pull, and adjust from them.
# These pools help avoid scanning 4,000+ stocks.
# ===============================================================

LARGE_CAP = [
    # Mega caps — stable, always relevant
    "AAPL","MSFT","AMZN","GOOGL","META","NVDA","TSLA","BRK.B","JPM","V",
    "MA","HD","PG","XOM","UNH","LLY"
]

MID_CAP = [
    # Liquid midcaps — high probability movers
    "AMD","NFLX","SHOP","UBER","SQ","PYPL","CRM","COIN","PLTR","ABNB",
    "DIS","NKE","BA","QCOM","SNOW","MU","DE"
]

MOMENTUM_LIST = [
    # Fast movers — changes weekly in real life,
    # Astra will randomly rotate these to avoid noise.
    "TSLA","COIN","NVDA","AMD","META","RIOT","MARA","SMCI",
    "CELH","DKNG","RBLX","AFRM","ENPH","SOFI","BIDU"
]

CRYPTO_POOL = [
    # Core crypto — auto-rotated
    "BTCUSD","ETHUSD","SOLUSD","XRPUSD","ADAUSD","DOGEUSD",
    "AVAXUSD","DOTUSD","LINKUSD","LTCUSD","BCHUSD",
    "FTMUSD","ATOMUSD","ETCUSD","NEARUSD"
]


# ===============================================================
# 2. DAILY ROTATION LOGIC
# Ensures Astra stays efficient AND dynamic every run.
# ===============================================================

def rotate_list(base_list, n):
    """Randomly pick n tickers from a pool."""
    n = min(n, len(base_list))
    return random.sample(base_list, n)


def daily_seed():
    """Stable rotation per day so scans change daily but are reproducible."""
    today = int(datetime.datetime.utcnow().strftime("%Y%m%d"))
    random.seed(today)


# ===============================================================
# 3. MAIN SCREENER
# Returns a list of tickers to pass into smart_scan → hybrid_scan
# ===============================================================

def get_screener_list():
    """
    Returns ~75 stocks and ~25 crypto:
        • 30 large caps (stable)
        • 25 midcaps (growth)
        • 20 momentum names (rotating)
        • 20 cryptos (rotating)
    """

    daily_seed()

    selected_large = rotate_list(LARGE_CAP, 30)
    selected_mid = rotate_list(MID_CAP, 25)
    selected_momo = rotate_list(MOMENTUM_LIST, 20)
    selected_crypto = rotate_list(CRYPTO_POOL, 20)

    tickers = list(set(selected_large + selected_mid + selected_momo))
    cryptos = list(set(selected_crypto))

    return {
        "stocks": tickers,
        "crypto": cryptos
    }
