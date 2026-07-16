import unittest

from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_forward_baseline_v1,
    build_unified_position_lifecycle_decision_v1,
    build_position_shadow_twin_v1,
    classify_position_cohort_v1,
    estimate_legacy_provisional_horizon_v1,
    retrieve_position_lifecycle_evidence_v1,
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

    def test_bounded_context_is_retrieved_matched_and_consumed(self):
        evidence = retrieve_position_lifecycle_evidence_v1(
            {"symbol": "ABC", "qty": 1, "market_value": 10, "current_price": 10},
            evidence_context={
                "symbol_profile": {"sample_size": 4},
                "historical_similarity": "linked", "replay_evidence": "linked",
                "opportunity_cost_state": "LOW", "replacement_analysis": {"candidate": {"symbol": "XYZ"}},
            },
        )
        self.assertGreaterEqual(evidence["consumed_count"], 5)
        self.assertFalse(next(row for row in evidence["evidence_rows"] if row["source"] == "shadow")["available"])

    def test_shadow_is_contextual_and_cannot_make_action_ready(self):
        decision = build_unified_position_lifecycle_decision_v1(
            {"symbol": "ABC", "qty": 1, "market_value": 10, "current_price": 10, "days_held": 31, "unrealized_return_pct": -1},
            evidence_context={"shadow_evidence": {"supports": "exit"}},
        )
        self.assertEqual(decision["shadow_guidance"], "SHADOW_SUPPORTS_EXIT_REVIEW")
        self.assertFalse(decision["paper_action_ready"])

    def test_supported_forecast_remains_range_based(self):
        decision = build_unified_position_lifecycle_decision_v1(
            {"symbol": "ABC", "qty": 1, "market_value": 10, "current_price": 10, "unrealized_return_pct": 1},
            evidence_context={"expected_upside_range": [1.0, 3.0], "expected_downside_range": [-2.0, -1.0]},
        )
        self.assertEqual(decision["predictive_forecast_state"], "FORECAST_COMPLETE")
        self.assertEqual(decision["expected_remaining_upside_range"], [1.0, 3.0])

    def test_legacy_baseline_horizon_and_shadow_are_forward_only(self):
        position = {"symbol": "ABC", "qty": 1, "market_value": 10, "current_price": 10, "days_held": 20, "legacy_activation_timestamp": "2026-07-16T00:00:00Z"}
        baseline = build_legacy_forward_baseline_v1(position)
        horizon = estimate_legacy_provisional_horizon_v1(position, baseline)
        twin = build_position_shadow_twin_v1(position, baseline, horizon)
        self.assertEqual(baseline["original_horizon"], "UNKNOWN")
        self.assertEqual(horizon["provisional_horizon"], "SWING_MULTI_WEEK")
        self.assertEqual(twin["state"], "POSITION_SHADOW_TWIN_ACTIVE")
        self.assertTrue(all(not row["broker_mutation"] for row in twin["scenarios"]))

    def test_legacy_canary_is_fail_closed_without_runtime_switch(self):
        decision = build_unified_position_lifecycle_decision_v1(
            {"symbol": "ABC", "qty": 1, "market_value": 10, "current_price": 10, "days_held": 31, "unrealized_return_pct": -1},
        )
        self.assertEqual(decision["legacy_canary_policy"]["state"], "LEGACY_CANARY_ADVISORY_ONLY")
        self.assertFalse(decision["legacy_canary_policy"]["paper_action_ready"])


if __name__ == "__main__":
    unittest.main()
