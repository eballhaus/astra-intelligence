import unittest

from server_extend import _day_lane_owned_positions_v1


class DayLaneSameSessionExitContractTests(unittest.TestCase):
    def test_only_explicit_day_positions_are_owned_by_day_worker(self):
        rows = [
            {"symbol": "DAY", "lane_id": "DAY", "same_session_exit_required": True},
            {"symbol": "SWING", "lane_id": "SWING", "same_session_exit_required": False},
            {"symbol": "CRYPTO", "lane_id": "CRYPTO", "same_session_exit_required": True},
            {"symbol": "LEGACY", "symbol_only": True},
        ]
        self.assertEqual([row["symbol"] for row in _day_lane_owned_positions_v1(rows)], ["DAY"])


if __name__ == "__main__":
    unittest.main()
