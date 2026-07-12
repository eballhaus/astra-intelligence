import unittest

from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status


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


if __name__ == "__main__":
    unittest.main()
