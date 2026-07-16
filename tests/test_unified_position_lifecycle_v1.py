import unittest

from engine.astra_unified_position_lifecycle_v1 import (
    build_unified_position_lifecycle_decision_v1,
    classify_position_cohort_v1,
)


class UnifiedPositionLifecycleTests(unittest.TestCase):
    def test_legacy_and_complete_contract_cohorts_are_separate(self):
        self.assertEqual(classify_position_cohort_v1({"symbol": "OLD", "qty": 1, "market_value": 10})["cohort"], "LEGACY_PRE_CONTRACT_POSITION")
        self.assertEqual(classify_position_cohort_v1({"symbol": "NEW", "qty": 1, "market_value": 10, "candidate_id": "c", "contract_id": "k"})["cohort"], "NEW_COMPLETE_CONTRACT_POSITION")

    def test_dust_is_not_classified_as_normal_hold(self):
        decision = build_unified_position_lifecycle_decision_v1({"symbol": "DUST", "qty": 0.0001, "market_value": 0.001})
        self.assertEqual(decision["classification"], "DUST_CLEANUP_REVIEW")
        self.assertTrue(decision["advisory_only"])

    def test_day_cannot_silently_convert_to_swing(self):
        decision = build_unified_position_lifecycle_decision_v1({"symbol": "DAY", "qty": 1, "market_value": 10, "lane_id": "DAY", "intended_horizon": "day_trade", "days_held": 2, "current_price": 10, "unrealized_return_pct": -2})
        self.assertEqual(decision["horizon_state"], "HORIZON_EXPIRED")
        self.assertEqual(decision["current_recommended_horizon"], "day_trade")

    def test_action_worthy_state_remains_policy_blocked(self):
        decision = build_unified_position_lifecycle_decision_v1({"symbol": "OLD", "qty": 1, "market_value": 10, "days_held": 31, "current_price": 10, "unrealized_return_pct": -1})
        self.assertEqual(decision["classification"], "EXIT_REVIEW")
        self.assertFalse(decision["paper_action_ready"])


if __name__ == "__main__":
    unittest.main()
