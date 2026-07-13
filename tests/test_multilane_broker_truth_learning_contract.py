import unittest

from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status


class MultilaneBrokerTruthLearningContractTests(unittest.TestCase):
    def test_only_complete_fill_linkage_counts_as_broker_truth_and_etf_is_a_cohort(self):
        complete = {
            "symbol": "SPY", "truth_quality": "BROKER_CONFIRMED_COMPLETE", "entry_fill_id": "buy-1",
            "exit_fill_id": "sell-1", "entry_order_id": "buy-order-1", "exit_order_id": "sell-order-1",
            "lifecycle_id": "life-1", "asset_class": "equity", "instrument_type": "ETF",
            "paper_entry_horizon_style": "swing_trade",
        }
        incomplete = {"symbol": "BTC/USD", "asset_class": "crypto", "truth_quality": "BROKER_CONFIRMED_COMPLETE"}
        payload = build_multilane_operational_status(
            candidates=[], open_positions=[], broker_truth_records=[complete, incomplete],
            source_metadata={"candidate_freshness_status": "CURRENT"},
        )
        counts = payload["broker_truth_counts"]
        self.assertEqual(counts["total_broker_confirmed_complete"], 1)
        self.assertEqual(counts["etf_broker_confirmed_complete"], 1)
        self.assertEqual(counts["crypto_broker_confirmed_complete"], 0)
        self.assertTrue(counts["cohort_counts_overlap_total"])


if __name__ == "__main__":
    unittest.main()
