import os
import unittest
from unittest.mock import patch

from server_extend import _day_lane_pilot_config_v1


class DayLanePilotActivationMasterContractTests(unittest.TestCase):
    def test_switch_is_explicit_and_human_gated(self):
        # Activation is a local runtime choice. Verify the safe disabled branch
        # explicitly so this contract remains valid when an approved .env
        # enables the paper-only pilot for a live validation window.
        with patch.dict(os.environ, {"ASTRA_DAY_LANE_PILOT_ENABLED": "0"}, clear=False):
            config = _day_lane_pilot_config_v1()
        self.assertFalse(config["day_lane_pilot_enabled"])
        self.assertTrue(config["human_approval_required"])
        self.assertFalse(config["automatic_expansion_enabled"])
        self.assertEqual(config["day_lane_max_open_positions"], 1)
        self.assertEqual(config["day_lane_max_completed_trades_per_session"], 2)

    def test_approved_enablement_keeps_level_one_and_human_review(self):
        with patch.dict(os.environ, {"ASTRA_DAY_LANE_PILOT_ENABLED": "1"}, clear=False):
            config = _day_lane_pilot_config_v1()
        self.assertTrue(config["day_lane_pilot_enabled"])
        self.assertTrue(config["human_approval_required"])
        self.assertFalse(config["automatic_expansion_enabled"])
        self.assertEqual(config["day_lane_max_open_positions"], 1)
        self.assertEqual(config["day_lane_max_completed_trades_per_session"], 2)


if __name__ == "__main__":
    unittest.main()
