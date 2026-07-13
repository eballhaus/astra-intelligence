import unittest
from unittest.mock import patch

from engine.paper_opportunity_allocation_engine_v1 import PaperOpportunityAllocationEngineV1


class DayTradingPaperLaneContractTests(unittest.TestCase):
    def test_day_lane_is_advisory_and_zero_trades_are_valid(self):
        engine = PaperOpportunityAllocationEngineV1(state_dir="/tmp/astra-day-lane-contract")
        with patch.dict("os.environ", {"ASTRA_DAY_LANE_PILOT_ENABLED": "0"}, clear=False):
            result = engine.day_lane_governance(rows=[], open_positions=[])
        self.assertFalse(result["day_lane_execution_enabled"])
        self.assertTrue(result["zero_qualifying_trades_valid"])
        self.assertTrue(result["ceiling_is_not_a_quota"])
        self.assertEqual(result["capital_book_id"], "paper_day_learning")

    def test_existing_swing_and_crypto_positions_are_only_cross_lane_duplicate_checks(self):
        engine = PaperOpportunityAllocationEngineV1(state_dir="/tmp/astra-day-lane-duplicate")
        rows = [{"symbol": "NVDA", "paper_entry_horizon_style": "day_trade", "confidence": 82, "paper_ready": True}]
        positions = [
            {"symbol": "NVDA", "paper_entry_horizon_style": "swing_trade"},
            {"symbol": "BTC/USD", "asset_class": "crypto"},
        ]
        result = engine.day_lane_governance(rows=rows, open_positions=positions)
        self.assertEqual(result["eligible_candidate_supply"], 0)
        self.assertEqual(result["rejection_reasons"]["DUPLICATE_SYMBOL_CROSS_LANE"], 1)
        self.assertFalse(result["exit_behavior_changed"])
