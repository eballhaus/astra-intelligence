"""
Astra Intelligence – Centralized environment key loader.
All keys come from system environment variables.
"""

import os

ALPHA_VANTAGE_API_KEY = os.getenv("ALPHA_VANTAGE_API_KEY")
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")
FINNHUB_API_KEY = os.getenv("FINNHUB_API_KEY")
EODHD_API_KEY = os.getenv("EODHD_API_KEY")
MORALIS_API_KEY = os.getenv("MORALIS_API_KEY")
DATAJOCKEY_API_KEY = os.getenv("DATAJOCKEY_API_KEY")
SIMFIN_API_KEY = os.getenv("SIMFIN_API_KEY")
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")
NASDAQ_API_KEY = os.getenv("NASDAQ_API_KEY")
