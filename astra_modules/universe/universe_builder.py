"""
universe_builder.py — Phase-90

Constructs a safe and dynamic market universe for Astra Intelligence.

Includes:
 • Core S&P 100 tickers
 • Liquid growth names
 • High-volume ETFs
 • Crypto majors
 • Guardian-safe fallbacks
"""

import random


class UniverseBuilder:
    def __init__(self):
        # ---------------------------------------
        # PRIMARY HIGH-QUALITY STOCK UNIVERSE
        # ---------------------------------------
        self.core_stocks = [
            # S&P 100 anchors
            "AAPL", "MSFT", "AMZN", "GOOGL", "META", "NVDA", "TSLA",
            "BRK.B", "JPM", "JNJ", "V", "PG", "HD", "MA", "XOM",
            "AVGO", "UNH", "CVX", "ABBV", "LLY", "PEP", "KO",
            # High-growth leaders
            "AMD", "NFLX", "CRM", "ADBE", "COST", "PYPL", "QCOM",
            "TSM", "BABA", "SHOP", "INTC", "NKE", "WMT",
        ]

        # ---------------------------------------
        # ETF Universe
        # ---------------------------------------
        self.etfs = [
            "SPY", "QQQ", "VTI", "IWM", "DIA",
            "XLK", "XLF", "XLY", "XLV", "XLE", "XLP",
        ]

        # ---------------------------------------
        # Crypto Universe
        # ---------------------------------------
        self.crypto = [
            "BTC-USD", "ETH-USD", "SOL-USD", "ADA-USD",
            "XRP-USD", "DOGE-USD", "DOT-USD",
        ]

        # ---------------------------------------
        # Fallback simplified universe
        # ---------------------------------------
        self.fallback = [
            "AAPL", "MSFT", "SPY", "QQQ", "BTC-USD",
        ]

    # ---------------------------------------------------------
    # SAFE UNIVERSE BUILDER
    # ---------------------------------------------------------
    def build_universe(self):
        """
        Returns a mixed list of stocks + ETFs + crypto.

        Always returns AT LEAST the fallback list.
        """
        try:
            # Mix stock universe
            stock_sample = random.sample(
                self.core_stocks,
                min(20, len(self.core_stocks)),
            )

            # Add ETFs + Crypto
            universe = stock_sample + self.etfs + self.crypto

            # Remove duplicates and None
            universe = list({t for t in universe if t})
            return universe

        except Exception:
            # On any failure, return safe fallback
            return self.fallback
