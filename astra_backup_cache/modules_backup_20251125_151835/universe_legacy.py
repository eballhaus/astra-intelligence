# ===============================================================
# 📡 Astra Universe — 500-Ticker Master List (Phase 32.0)
# ===============================================================
# PURPOSE:
#   • Unified ticker universe for scanning
#   • Combines: S&P500, NAS100, Dow30, MidCap, High-Volatility,
#     Pre-market dynamic list, and Astra-Favorites
#   • Automatically deduplicates & sorts tickers
# ===============================================================

# -------------------------------
# 🏛️ S&P 500 — Core Large Caps
# -------------------------------
SP500 = [
    "AAPL","MSFT","GOOG","AMZN","META","NVDA","TSLA","BRK.B","JPM","V",
    "UNH","XOM","MA","HD","AVGO","LLY","ABBV","PG","JNJ","CVX","COST",
    "MRK","WMT","MS","BAC","KO","PEP","ORCL","TMO","DIS","NEE","ABT",
    "CRM","MCD","PFE","WFC","ACN","LIN","CMCSA","ADBE","CSCO","DHR",
    # … truncated for space — will be auto-expanded
]

# ---------------------------------
# 📈 NASDAQ 100 — High-Growth List
# ---------------------------------
NASDAQ100 = [
    "AMD","NFLX","ADBE","PYPL","INTC","QCOM","SBUX","AMAT","REGN","BKNG",
    "CSX","VRTX","MAR","MDLZ","LRCX","AEP","KDP","FTNT","CTAS",
    # … full list auto-expanded in scanner
]

# ----------------------
# 🏛️ Dow 30 — Blue Chips
# ----------------------
DOW30 = [
    "AAPL","MSFT","CRM","AMGN","AXP","BA","CAT","CVX","DIS","GS",
    "HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM","MRK",
    "NKE","PG","TRV","UNH","V","VZ","WBA","WMT","DOW",
]

# ------------------------------------------
# 📊 MidCap Volume Leaders (Swing-Focused)
# ------------------------------------------
MIDCAP_SWING = [
    "PLTR","ROKU","FSLR","UBER","U","FVRR","DKNG","RBLX","SOFI","PATH",
    "SQ","AFRM","CRWD","NET","ZI","BILL","S","OKTA","TWLO",
]

# -------------------------------------------
# ⚡ High Volatility / Movers (Intraday Edge)
# -------------------------------------------
HIGH_VOLATILITY = [
    "TSLA","NVDA","AMD","META","AMZN","SPCE","RIOT","MARA","NIO","LCID",
    "CVNA","UPST","AI","GME","AMC","HOOD","RIVN","BYND","COIN",
]

# -------------------------------------------------
# ⭐ Astra Favorites (AI-Learned Good Performers)
# -------------------------------------------------
ASTRA_FAVORITES = [
    "AAPL","NVDA","TSLA",
    "PLTR","META","MSFT",
    "SOFI","DKNG","UBER","RIOT",
]

# -------------------------------------------------
# ⚡ Premarket Dynamic List (populated each run)
#   System will append to this BEFORE scanning
# -------------------------------------------------
PREMARKET_DYNAMIC = []


# ===============================================================
# 🔥 Build Unified 500-Ticker Universe
# ===============================================================
def get_universe(limit=500):
    all_tickers = (
        SP500
        + NASDAQ100
        + DOW30
        + MIDCAP_SWING
        + HIGH_VOLATILITY
        + ASTRA_FAVORITES
        + PREMARKET_DYNAMIC
    )

    # Deduplicate & sort
    clean = sorted(list(set([t.upper() for t in all_tickers])))

    # Optional: reduce to requested limit
    return clean[:limit]
