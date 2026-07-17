import unittest

from engine.astra_unified_position_lifecycle_v1 import (
    build_legacy_forward_baseline_v1,
    build_legacy_swing_canary_pre_submit_v1,
    build_unified_position_lifecycle_decision_v1,
    build_position_shadow_twin_v1,
    classify_position_cohort_v1,
    estimate_legacy_provisional_horizon_v1,
    evaluate_legacy_swing_canary_eligibility_v1,
    legacy_swing_canary_configuration_v1,
    retrieve_position_lifecycle_evidence_v1,
    select_legacy_swing_canary_candidate_v1,
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

    def test_disabled_canary_configuration_is_exact_and_fail_closed(self):
        config = legacy_swing_canary_configuration_v1()
        self.assertEqual(config["policy_id"], "LEGACY_SWING_CONTROLLED_PAPER_CANARY_V1")
        self.assertFalse(config["enabled"])
        self.assertTrue(config["kill_switch"])
        self.assertEqual(config["max_canary_notional_usd"], 100.0)

    def test_technical_eligibility_runs_while_execution_is_disabled(self):
        config = legacy_swing_canary_configuration_v1()
        position = {"symbol": "ABC", "asset_id": "asset-abc", "qty": 5, "current_price": 10, "paper_mode_verified": True}
        decision = {
            "position_id": "asset-abc", "classification": "THESIS_BROKEN", "forecast_confidence": 0.9,
            "current_direct_confirmation": True, "direct_confirmation_confidence": 0.9,
            "forward_baseline": {"baseline_id": "legacy-forward:asset-abc", "legacy_activation_timestamp": "2026-07-16T00:00:00Z"},
            "shadow_twin": {"state": "POSITION_SHADOW_TWIN_ACTIVE"},
            "provisional_horizon": {"provisional_horizon": "SWING_MULTI_WEEK"},
        }
        result = evaluate_legacy_swing_canary_eligibility_v1(position, decision, config)
        self.assertTrue(result["technical_eligibility"])
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(result["final_state"], "KILL_SWITCH_ACTIVE")

    def test_advisory_state_is_not_technically_eligible(self):
        config = legacy_swing_canary_configuration_v1()
        decision = {
            "position_id": "asset", "classification": "EXIT_REVIEW", "forecast_confidence": 0.99,
            "current_direct_confirmation": True, "forward_baseline": {"baseline_id": "b", "legacy_activation_timestamp": "x"},
            "shadow_twin": {"state": "POSITION_SHADOW_TWIN_ACTIVE"}, "provisional_horizon": {"provisional_horizon": "SWING_4_7_DAYS"},
        }
        result = evaluate_legacy_swing_canary_eligibility_v1({"symbol": "ABC", "asset_id": "asset", "qty": 1, "current_price": 10}, decision, config)
        self.assertFalse(result["technical_eligibility"])
        self.assertIn("ADVISORY_CLASSIFICATION", result["eligibility_failures"])

    def test_selection_is_stable_across_input_order_and_pre_submit_is_non_executing(self):
        config = legacy_swing_canary_configuration_v1()
        decision = {
            "position_id": "asset-a", "symbol": "AAA", "classification": "THESIS_BROKEN", "forecast_confidence": 0.95,
            "current_direct_confirmation": True, "direct_confirmation_confidence": 0.95,
            "forward_baseline": {"baseline_id": "baseline-a", "legacy_activation_timestamp": "2026-07-16T00:00:00Z"},
            "shadow_twin": {"state": "POSITION_SHADOW_TWIN_ACTIVE"}, "provisional_horizon": {"provisional_horizon": "SWING_MULTI_WEEK"},
            "evidence_rows": [], "lane": "SWING", "cohort": "LEGACY_PRE_CONTRACT_POSITION",
        }
        position = {"symbol": "AAA", "asset_id": "asset-a", "qty": 20, "current_price": 10, "paper_mode_verified": True}
        eligibility = evaluate_legacy_swing_canary_eligibility_v1(position, decision, config)
        row_a = {"position_id": "asset-a", "symbol": "AAA", "technical_eligibility": True, "decision": decision, "eligibility": eligibility}
        row_b = {"position_id": "asset-b", "symbol": "BBB", "technical_eligibility": True, "decision": {**decision, "position_id": "asset-b", "symbol": "BBB", "forecast_confidence": 0.85}, "eligibility": {**eligibility, "decision_confidence": 0.85}}
        first = select_legacy_swing_canary_candidate_v1([row_b, row_a])
        second = select_legacy_swing_canary_candidate_v1([row_a, row_b])
        self.assertEqual(first["selected_candidate"]["position_id"], second["selected_candidate"]["position_id"])
        pre_submit = build_legacy_swing_canary_pre_submit_v1(position=position, lifecycle_decision=decision, eligibility=eligibility, selection=first, configuration=config)
        self.assertIsNotNone(pre_submit)
        self.assertFalse(pre_submit["execution_authorized"])
        self.assertFalse(pre_submit["writer_adapter_required"])
        self.assertEqual(pre_submit["pre_submit_state"], "LEGACY_SWING_CANARY_PRE_SUBMIT_READY")
        self.assertEqual(pre_submit["writer_contract_status"], "ADAPTER_MAPPING_VALID")
        self.assertLessEqual(pre_submit["proposed_notional"], 100.0)


if __name__ == "__main__":
    unittest.main()
