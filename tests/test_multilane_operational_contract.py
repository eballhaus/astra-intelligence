import unittest

from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status
from engine.astra_paper_provider_cortex_completion_v1 import build_truth_acceleration_oversight


class MultilaneOperationalContractTests(unittest.TestCase):
    def test_reconstruction_is_not_current_candidate_or_broker_truth(self):
        payload = build_multilane_operational_status(
            candidates=[{"symbol": "OLD", "evidence_class": "MEDIUM_CONFIDENCE_RECONSTRUCTED"}],
            open_positions=[], broker_truth_records=[], source_metadata={"candidate_freshness_status": "CURRENT"},
        )
        self.assertEqual(payload["lanes"]["swing"]["current_candidates"], 0)
        self.assertEqual(payload["broker_truth_counts"]["total_broker_confirmed_complete"], 0)
        self.assertEqual(payload["broker_actions_used"], 0)

    def test_day_selection_uses_autopilot_trace_not_candidate_flag(self):
        candidate = {"symbol": "NVDA", "paper_entry_horizon_style": "day_trade", "candidate_id": "c1"}
        payload = build_multilane_operational_status(
            candidates=[candidate], open_positions=[], broker_truth_records=[],
            autopilot_trace={"per_candidate_decision_trace": [{"symbol": "NVDA", "selected": True, "order_ready": True}]},
            source_metadata={"candidate_freshness_status": "CURRENT"},
            day_config={"capital_configured": True, "day_lane_pilot_enabled": True},
        )
        self.assertEqual(payload["lanes"]["day"]["actual_selected_candidates"], 1)
        self.assertEqual(payload["lanes"]["day"]["order_ready_candidates"], 1)
        self.assertTrue(payload["day_selection_semantics"]["diagnostic_selection_is_not_actual_selection"])

    def test_etf_is_a_cohort_not_a_separate_execution_lane(self):
        payload = build_multilane_operational_status(
            candidates=[{"symbol": "XLK", "instrument_type": "ETF", "paper_entry_horizon_style": "day_trade", "candidate_id": "etf-1"}],
            open_positions=[], broker_truth_records=[],
            source_metadata={"candidate_freshness_status": "CURRENT"},
            day_config={"capital_configured": True, "day_lane_pilot_enabled": True},
        )
        self.assertIn("day_etf", payload["cohorts"])
        self.assertEqual(payload["cohorts"]["day_etf"]["canonical_lane"], "DAY")
        self.assertTrue(payload["cohorts"]["day_etf"]["lane_contract"]["etf_is_cohort_not_execution_lane"])

    def test_crypto_freshness_is_the_first_blocker_when_no_current_candidate_exists(self):
        payload = build_multilane_operational_status(
            candidates=[], open_positions=[], broker_truth_records=[],
            source_metadata={"candidate_freshness_status": "MISSING"},
        )
        blocker = payload["lanes"]["crypto"]["first_causal_blocker"]
        self.assertEqual(blocker["code"], "CANDIDATE_FRESHNESS_NOT_READY")
        self.assertEqual(payload["lanes"]["crypto"]["lifecycle_funnel"]["orders_submitted"], 0)

    def test_exact_trace_gate_replaces_generic_rejection_summary(self):
        candidate = {"symbol": "NVDA", "paper_entry_horizon_style": "day_trade", "candidate_id": "c1"}
        payload = build_multilane_operational_status(
            candidates=[candidate], open_positions=[], broker_truth_records=[],
            autopilot_trace={"per_candidate_decision_trace": [{
                "symbol": "NVDA", "lane_id": "DAY", "eligible": False,
                "decision_reason": "quality_confidence_too_low",
                "eligibility_gate_attribution_v1": {
                    "first_failing_gate": {
                        "code": "CONFIDENCE_BELOW_THRESHOLD",
                        "owner": "PaperAutopilot commitment gate",
                        "input_value": "quality_confidence_too_low",
                        "validity": "VALID_STRATEGY_REJECTION",
                    },
                },
            }]},
            source_metadata={"candidate_freshness_status": "CURRENT"},
            day_config={"capital_configured": True, "day_lane_pilot_enabled": True},
        )
        blocker = payload["lanes"]["day"]["first_causal_blocker"]
        self.assertEqual(blocker["code"], "CONFIDENCE_BELOW_THRESHOLD")
        self.assertEqual(blocker["validity"], "VALID_STRATEGY_REJECTION")

    def test_flat_truth_state_is_contextual_when_only_valid_rejections_exist(self):
        payload = build_multilane_operational_status(
            candidates=[{"symbol": "NVDA", "paper_entry_horizon_style": "day_trade", "candidate_id": "c1"}],
            open_positions=[], broker_truth_records=[],
            autopilot_trace={"per_candidate_decision_trace": [{
                "symbol": "NVDA", "lane_id": "DAY", "eligible": False,
                "decision_reason": "quality_confidence_too_low",
                "eligibility_gate_attribution_v1": {"first_failing_gate": {"code": "CONFIDENCE_BELOW_THRESHOLD"}},
            }]},
            source_metadata={"candidate_freshness_status": "CURRENT"},
            day_config={"capital_configured": True, "day_lane_pilot_enabled": True},
        )
        self.assertEqual(
            payload["truth_production_scoreboard"]["flat_truth_escalation_state"],
            "VALID_GATE_REJECTIONS",
        )

    def test_truth_independence_keeps_raw_truths_but_discounts_shared_context(self):
        truth = {
            "evidence_class": "BROKER_CONFIRMED_COMPLETE", "lane_id": "CRYPTO", "asset_class": "crypto",
            "symbol": "BTC/USD", "strategy_cohort": "CRYPTO_SEPARATE", "market_regime": "RISK_ON",
            "entry_timestamp": "2026-07-18T12:00:00Z", "entry_fill_id": "entry-1", "exit_fill_id": "exit-1",
            "entry_order_id": "order-1", "exit_order_id": "order-exit-1", "lifecycle_id": "life-1",
            "broker_residual_zero_confirmed": True,
        }
        second = {**truth, "truth_id": "truth-2", "entry_fill_id": "entry-2", "exit_fill_id": "exit-2", "entry_order_id": "order-2", "exit_order_id": "order-exit-2", "lifecycle_id": "life-2"}
        payload = build_multilane_operational_status(
            candidates=[], open_positions=[], broker_truth_records=[truth, second],
            source_metadata={"candidate_freshness_status": "CURRENT"},
        )
        independence = payload["truth_independence"]
        self.assertEqual(independence["raw_completed_broker_truths"], 2)
        self.assertEqual(independence["quality_adjusted_independent_truths"], 1.0)
        self.assertEqual(len(independence["contributions"]), 2)
        self.assertEqual(independence["contributions"][0]["independence_weight"], 0.5)

    def test_confirmed_closed_symbol_still_counted_is_repairable_capacity_defect(self):
        payload = build_multilane_operational_status(
            candidates=[],
            open_positions=[{"symbol": "AAPL", "lane_id": "SWING"}],
            broker_truth_records=[],
            source_metadata={"candidate_freshness_status": "CURRENT"},
            capacity_snapshot={"capacity_authority_state": "CURRENT", "lanes": {"swing": {"positions_used": 1, "positions_remaining": 0, "configured_position_limit": 1, "reserve_state": "AVAILABLE", "capacity_authority_state": "CURRENT"}}},
            position_review_rows=[{"symbol": "AAPL", "reconciliation_state": "RECONCILED_CLOSED", "broker_position_quantity": 0}],
        )
        self.assertEqual(payload["capacity_recycling_integrity"]["state"], "REPAIRABLE_CAPACITY_DEFECT")
        self.assertEqual(payload["governance_truth_acceleration_findings"][0]["code"], "REPAIRABLE_CAPACITY_DEFECT")

    def test_lane_is_not_certified_when_capacity_arithmetic_is_unverified(self):
        payload = build_multilane_operational_status(
            candidates=[], open_positions=[], broker_truth_records=[],
            source_metadata={"candidate_freshness_status": "CURRENT"},
            capacity_snapshot={"capacity_authority_state": "CURRENT", "lanes": {"day": {"capacity_authority_state": "CURRENT"}}},
        )
        day = payload["parallel_lane_readiness"]["certifications"]["DAY_EQUITY"]
        self.assertEqual(day["state"], "BLOCKED_FAIL_CLOSED")
        self.assertIn("CAPACITY_ARITHMETIC_NOT_VERIFIED", day["exact_blockers"])

    def test_cortex_proposals_remain_governance_gated_and_cannot_change_policy(self):
        payload = build_truth_acceleration_oversight(
            lanes={"day": {"eligible_candidates": 2, "actual_selected_candidates": 0, "operational_status": "ACTIVE"}},
            capacity_integrity={"day": {"state": "PASS"}},
        )
        self.assertEqual(payload["controller_state"], "ACTIVE_OBSERVE_AND_GOVERN")
        self.assertTrue(payload["proposals"])
        self.assertFalse(payload["proposals"][0]["applied"])
        self.assertFalse(payload["direct_uncontrolled_mutation"])
        self.assertIn("confidence_threshold", payload["prohibited_automatic_changes"])


if __name__ == "__main__":
    unittest.main()
