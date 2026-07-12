import unittest

from server_extend import _day_lane_pilot_readiness_payload_v1


class DayLaneSelectionHandoffContractTests(unittest.TestCase):
    def test_eligible_current_candidate_has_explainable_selection_blocker(self):
        payload = _day_lane_pilot_readiness_payload_v1({
            "pladeu_candidate_rows": [{
                "symbol": "NVDA", "lane_id": "DAY", "trade_style": "day_trade",
                "intended_horizon": "intraday", "asset_class": "equity",
                "candidate_id": "c1", "recommendation_id": "r1",
            }],
            "pladeu_open_positions": [],
            "pladeu_day_lane_allocation": {
                "capital_book_id": "paper_day_learning", "cross_lane_exact_symbol_check": True,
                "same_session_close_posture": "authorized",
                "diversity_ceilings": {"one_sector": 2, "one_strategy_cohort": 2},
                "breakdown": {"correlation_cluster": {}},
            },
            "pladeu_candidate_source_metadata": {"candidate_freshness_status": "CURRENT", "market_session_status": "regular_hours"},
            "day_lane_pilot_config": {"capital_configured": True, "day_lane_pilot_enabled": False, "day_lane_disable_switch": False, "human_approval_required": True},
            "paper_autopilot_handoff_proof": {"proven": False},
        })
        self.assertEqual(payload["eligible_day_candidates"], 1)
        self.assertEqual(payload["selected_day_candidates"], 0)
        self.assertEqual(payload["candidate_stage_trace"][0]["exact_blocker"], "day_lane_pilot_disabled_pending_human_activation")


if __name__ == "__main__":
    unittest.main()
