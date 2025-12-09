# -*- coding: utf-8 -*-
"""
Astra Intelligence — API Keys Forwarder (v2.0)
------------------------------------------------
This file ensures compatibility for all modules that import API keys
from astra_modules.api_keys while keeping the real values defined
safely in core/api_keys.py.
"""

from astra_modules.core.api_keys import (ALPHA_VANTAGE_API_KEY, EODHD_API_KEY,
                                         FINNHUB_API_KEY, FMP_API_KEY,
                                         MORALIS_API_KEY, TWELVEDATA_API_KEY)

__all__ = [
    "ALPHA_VANTAGE_API_KEY",
    "FMP_API_KEY",
    "TWELVEDATA_API_KEY",
    "FINNHUB_API_KEY",
    "EODHD_API_KEY",
    "MORALIS_API_KEY",
]
