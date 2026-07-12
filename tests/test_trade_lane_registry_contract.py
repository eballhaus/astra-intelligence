import unittest

from engine.astra_trade_lane_registry_v1 import apply_trade_lane_contract
from engine.trade_lifecycle_tracker import _normalize_record


class TradeLaneRegistryContractTests(unittest.TestCase):
    def test_explicit_lane_contract_keeps_scalp_inside_day_book(self):
        payload = apply_trade_lane_contract(
            {"symbol": "NVDA", "paper_entry_horizon_style": "scalp", "recommendation_id": "rec-1"},
            now="2026-07-12T12:00:00Z",
        )
        self.assertEqual(payload["lane_id"], "DAY")
        self.assertEqual(payload["strategy_cohort"], "SCALP")
        self.assertEqual(payload["capital_book_id"], "paper_day_learning")
        self.assertTrue(payload["same_session_exit_required"])
        self.assertFalse(payload["overnight_allowed"])
        self.assertEqual(payload["lane_assignment_source"], "PRETRADE_EXPLICIT")

    def test_swing_crypto_and_etf_stay_in_their_intended_lanes(self):
        swing = apply_trade_lane_contract({"symbol": "AAPL", "paper_entry_horizon_style": "swing_trade"})
        crypto = apply_trade_lane_contract({"symbol": "BTC/USD", "asset_class": "crypto", "paper_entry_horizon_style": "day_trade"})
        etf = apply_trade_lane_contract({"symbol": "SPY", "asset_class": "etf", "paper_entry_horizon_style": "day_trade"})
        self.assertEqual((swing["lane_id"], swing["capital_book_id"]), ("SWING", "paper_swing"))
        self.assertEqual((crypto["lane_id"], crypto["capital_book_id"]), ("CRYPTO", "paper_crypto_separate"))
        self.assertEqual((etf["lane_id"], etf["strategy_cohort"]), ("DAY", "ETF_INTRADAY"))

    def test_legacy_contract_is_labeled_and_persists_through_lifecycle_normalization(self):
        legacy = apply_trade_lane_contract({"symbol": "QQQ", "trade_horizon_style": "intraday"}, legacy=True)
        record = _normalize_record({"lifecycle_id": "lane-1", **legacy})
        self.assertEqual(legacy["lane_assignment_source"], "LEGACY_INFERRED")
        self.assertEqual(record["lane_id"], "DAY")
        self.assertEqual(record["capital_book_id"], "paper_day_learning")
        self.assertIn("source_ranking_version", record)
