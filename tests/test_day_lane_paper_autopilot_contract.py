import unittest

from server_extend import day_lane_pilot_control_status_v1


class DayLanePaperAutopilotContractTests(unittest.TestCase):
    def test_control_status_is_observational_and_has_no_activation_mutation(self):
        payload = day_lane_pilot_control_status_v1(force=True)
        self.assertIsNone(payload["activation_mutation_endpoint"])
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertFalse(payload["behavior_safe_to_apply"])
        self.assertFalse(payload["broker_live_endpoint_allowed"])


if __name__ == "__main__":
    unittest.main()
