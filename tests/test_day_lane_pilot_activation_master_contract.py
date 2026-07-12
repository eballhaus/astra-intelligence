import unittest

from server_extend import _day_lane_pilot_config_v1


class DayLanePilotActivationMasterContractTests(unittest.TestCase):
    def test_default_contract_is_disabled_and_human_gated(self):
        config = _day_lane_pilot_config_v1()
        self.assertFalse(config["day_lane_pilot_enabled"])
        self.assertTrue(config["human_approval_required"])
        self.assertFalse(config["automatic_expansion_enabled"])
        self.assertEqual(config["day_lane_max_open_positions"], 1)
        self.assertEqual(config["day_lane_max_completed_trades_per_session"], 2)


if __name__ == "__main__":
    unittest.main()
