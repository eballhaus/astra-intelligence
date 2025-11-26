"""
scan_manager.py — Phase-90

Unifies:
 • UniverseBuilder
 • SmartScan
 • HybridScan
 • fetch_unified
 • StateBundleBuilder
 • AstraPrime
 • RankingEngine

Output:
 • Ranked predictions list for the Predictions Tab
"""

from astra_modules.universe.universe_builder import UniverseBuilder
from astra_modules.fetch_core.fetch_unified import fetch_unified
from astra_modules.scanners.smart_scan import SmartScan
from astra_modules.scanners.hybrid_scan import HybridScan

from astra_modules.core.astra_prime import AstraPrime
from astra_modules.state.state_bundle_builder import StateBundleBuilder
from astra_modules.ranking.ranking_engine import RankingEngine


class ScanManager:
    def __init__(self):
        self.universe = UniverseBuilder()
        self.smart = SmartScan()
        self.hybrid = HybridScan()
        self.prime = AstraPrime()
        self.builder = StateBundleBuilder()
        self.rank_engine = RankingEngine()

    # -------------------------------------------------------------
    # SAFE HELPERS
    # -------------------------------------------------------------
    def safe(self, val, default=None):
        if val is None:
            return default
        return val

    # -------------------------------------------------------------
    # MAIN SCAN PIPELINE
    # -------------------------------------------------------------
    def scan_universe(self):
        """
        Full end-to-end pipeline:
          1) Build universe
          2) Fetch OHLCV
          3) Run SmartScan + HybridScan
          4) Build state bundle
          5) Run AstraPrime
          6) Rank all results
        """
        tickers = self.universe.build_universe()
        packets = {}

        for ticker in tickers:
            # --------------------------------------------
            # FETCH DATA
            # --------------------------------------------
            df, meta = fetch_unified(ticker)

            if df is None or len(df) < 40:
                continue

            # --------------------------------------------
            # SCAN SIGNALS
            # --------------------------------------------
            try:
                smart_out = self.smart.scan(ticker, df)
            except Exception:
                smart_out = {}

            try:
                hybrid_out = self.hybrid.scan(ticker, df)
            except Exception:
                hybrid_out = {}

            # --------------------------------------------
            # BUILD BUNDLE
            # --------------------------------------------
            bundle = self.builder.build_bundle(
                ticker=ticker,
                df=df,
                fetch_meta=meta,
                psychology_data=smart_out.get("psychology"),
                catalyst_data=hybrid_out.get("catalyst"),
            )

            # --------------------------------------------
            # RUN ATRAPRIME
            # --------------------------------------------
            try:
                packet = self.prime.run(
                    ticker=ticker,
                    df=df,
                    fetch_meta=meta,
                    psychology_data=bundle["psychology"],
                    catalyst_data=bundle["catalyst"]
                )
            except Exception:
                continue

            packets[ticker] = packet

        # --------------------------------------------
        # RANK OUTPUT
        # --------------------------------------------
        return self.rank_engine.rank(packets)
