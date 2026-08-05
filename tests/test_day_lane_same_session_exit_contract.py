import unittest
from datetime import datetime, timezone

from server_extend import _day_lane_owned_positions_v1
from engine.market_session_execution_timing_v1 import MarketSessionExecutionTimingV1


class DayLaneSameSessionExitContractTests(unittest.TestCase):
    def test_only_explicit_day_positions_are_owned_by_day_worker(self):
        rows = [
            {"symbol": "DAY", "lane_id": "DAY", "same_session_exit_required": True},
            {"symbol": "SWING", "lane_id": "SWING", "same_session_exit_required": False},
            {"symbol": "CRYPTO", "lane_id": "CRYPTO", "same_session_exit_required": True},
            {"symbol": "LEGACY", "symbol_only": True},
        ]
        self.assertEqual([row["symbol"] for row in _day_lane_owned_positions_v1(rows)], ["DAY"])

    def test_early_close_is_not_treated_as_regular_afternoon_session(self):
        suite = MarketSessionExecutionTimingV1()
        # 18:05 UTC is 1:05 PM ET on the 2026 day after Thanksgiving.
        after_early_close = suite.session_status(datetime(2026, 11, 27, 18, 5, tzinfo=timezone.utc))
        self.assertEqual(after_early_close["market_session_mode"], "after_hours")
        self.assertFalse(after_early_close["paper_order_submission_allowed"])
        # A normal Wednesday remains open at the same local time.
        normal_day = suite.session_status(datetime(2026, 11, 25, 18, 5, tzinfo=timezone.utc))
        self.assertEqual(normal_day["market_session_mode"], "regular_market")
        self.assertTrue(normal_day["paper_order_submission_allowed"])


if __name__ == "__main__":
    unittest.main()
