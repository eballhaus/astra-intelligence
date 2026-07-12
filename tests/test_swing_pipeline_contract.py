import unittest

from engine.astra_multilane_operational_completion_v1 import build_multilane_operational_status


class SwingPipelineContractTests(unittest.TestCase):
    def test_swing_dry_run_reaches_order_ready_without_day_exit_contract(self):
        payload = build_multilane_operational_status(
            candidates=[{"symbol": "AAPL", "paper_entry_horizon_style": "swing_trade"}],
            open_positions=[], broker_truth_records=[],
            autopilot_trace={"per_candidate_decision_trace": [{"symbol": "AAPL", "selected": True, "order_ready": True}]},
            source_metadata={"candidate_freshness_status": "CURRENT"},
        )
        row = payload["lanes"]["swing"]["detailed_candidates"][0]
        self.assertEqual(row["operational_stage"], "ORDER_READY")
        self.assertFalse(row["same_session_exit_required"])
        self.assertTrue(row["overnight_allowed"])


if __name__ == "__main__":
    unittest.main()
