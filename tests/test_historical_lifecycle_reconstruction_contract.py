import unittest

from engine.astra_historical_lifecycle_reconstruction_v1 import reconstruct_lifecycles


class HistoricalLifecycleReconstructionContractTests(unittest.TestCase):
    def test_identifier_linkage_reconstructs_without_claiming_broker_truth(self):
        payload = reconstruct_lifecycles(
            {
                "candidate_decisions": [{"symbol": "NVDA", "recommendation_id": "rec-1", "asset_class": "equity", "lane_id": "DAY"}],
                "trade_lifecycle": [{"symbol": "NVDA", "recommendation_id": "rec-1", "asset_class": "equity", "lane_id": "DAY", "return_pct": 2.1}],
            }
        )
        record = payload["reconstructed_records"][0]
        self.assertEqual(record["evidence_class"], "HIGH_CONFIDENCE_RECONSTRUCTED")
        self.assertFalse(record["broker_truth_eligible"])
        self.assertTrue(payload["symbol_only_matching_disabled"])

    def test_symbol_only_and_conflicting_asset_class_matches_are_rejected(self):
        symbol_only = reconstruct_lifecycles({"lifecycle": [{"symbol": "NVDA", "return_pct": 1.0}]})
        conflict = reconstruct_lifecycles(
            {
                "a": [{"symbol": "BTC/USD", "recommendation_id": "same", "asset_class": "crypto"}],
                "b": [{"symbol": "BTC/USD", "recommendation_id": "same", "asset_class": "equity", "return_pct": 1.0}],
            }
        )
        self.assertEqual(symbol_only["rejected_records"][0]["evidence_class"], "AMBIGUOUS_REJECTED")
        self.assertEqual(conflict["rejected_records"][0]["reconstruction_reason"], "asset_class_conflict")

    def test_missing_exit_is_partial_not_fabricated(self):
        payload = reconstruct_lifecycles({"candidate": [{"symbol": "AAPL", "candidate_id": "cand-1", "lane_id": "SWING"}]})
        self.assertEqual(payload["reconstructed_records"][0]["evidence_class"], "PARTIAL_LIFECYCLE")
