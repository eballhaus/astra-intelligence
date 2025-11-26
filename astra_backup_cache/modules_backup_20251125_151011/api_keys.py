"""
Astra Intelligence — API Keys
This file defines ALL API_KEY names exactly as required across fetch_unified,
fetch_stock, fetch_crypto, fetch_etf, and universe_builder.
"""

# -------------------------------
# STOCK + MARKET DATA PROVIDERS
# -------------------------------
ALPHA_VANTAGE_API_KEY = "YJVYAJJSKKXF3ZQB"

FMP_API_KEY = "xbgYJPXsiwJ3coLczphQSBsghO7fTklM"   # Financial Modeling Prep

TWELVEDATA_API_KEY = "452b5c89fc8747d4803ee6bda5f891b2"

FINNHUB_API_KEY = "d42ee5hr01qorleqvvb0d42ee5hr01qorleqvvbg"

EODHD_API_KEY = "6904e7a2ced028.25933984"

# -------------------------------
# CRYPTO PROVIDERS
# -------------------------------
MORALIS_API_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJub25jZSI6IjUxNGFmZTQ0LTA5NjQtNGY0OS1iMzY0LTBhY2IzNGI1Yzc4MyIsIm9yZ0lkIjoiNDc5MDgy"
    "IiwidXNlcklkIjoiNDkyODc5IiwidHlwZUlkIjoiMGE0Yzg2YjMtNTFjMC00MzIwLWI2YzYtODU3NmY5NDhh"
    "ZWYyIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NjIwNTQ0NzYsImV4cCI6NDkxNzgxNDQ3Nn0."
    "qD2enThc_vEplne8qVqOxDJrCUherTPWb-jmpebvkyI"
)

# Backup crypto provider (some modules expect this)
COINGECKO_KEY = None  # Coingecko no longer requires an API key (left for compatibility)

# -------------------------------
# NEWS API (future use)
# -------------------------------
NEWS_API_KEY = None
