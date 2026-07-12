import unittest

from server_extend import _day_lane_pilot_readiness_payload_v1


class DayLanePilotReadinessContractTests(unittest.TestCase):
    def test_stale_candidates_are_not_current_and_pilot_is_disabled(self):
        payload = _day_lane_pilot_readiness_payload_v1({
            "pladeu_candidate_rows": [{
                "symbol": "NVDA", "lane_id": "DAY", "trade_style": "day_trade",
                "intended_horizon": "intraday", "asset_class": "stock",
                "candidate_id": "c-1", "recommendation_id": "r-1",
            }],
            "pladeu_open_positions": [],
            "pladeu_day_lane_allocation": {
                "capital_book_id": "paper_day_learning",
                "same_session_close_posture": "advisory_only_existing_governance_retained",
                "cross_lane_exact_symbol_check": True,
                "diversity_ceilings": {"one_sector": 2, "one_strategy_cohort": 2},
                "breakdown": {"correlation_cluster": {}},
            },
            "pladeu_candidate_source_metadata": {
                "candidate_source": "fixture",
                "candidate_freshness_status": "STALE",
                "market_session_status": "closed",
                "candidate_cache_age_seconds": 999,
            },
        })
        self.assertEqual(payload["classified_day_candidates"], 1)
        self.assertEqual(payload["current_day_candidates"], 0)
        self.assertFalse(payload["pilot_enabled"])
        self.assertIn("candidate_source_stale", payload["exact_blockers"])
        self.assertEqual(payload["broker_actions_used"], 0)
        self.assertFalse(payload["behavior_safe_to_apply"])

    def test_exact_cross_lane_overlap_is_a_blocker(self):
        payload = _day_lane_pilot_readiness_payload_v1({
            "pladeu_candidate_rows": [
                {"symbol": "NVDA", "lane_id": "DAY", "trade_style": "day_trade", "intended_horizon": "intraday", "asset_class": "stock", "candidate_id": "d", "recommendation_id": "rd"},
                {"symbol": "NVDA", "lane_id": "SWING", "trade_style": "swing", "intended_horizon": "swing", "asset_class": "stock", "candidate_id": "s", "recommendation_id": "rs"},
            ],
            "pladeu_open_positions": [],
            "pladeu_day_lane_allocation": {
                "capital_book_id": "paper_day_learning",
                "same_session_close_posture": "advisory_only_existing_governance_retained",
                "cross_lane_exact_symbol_check": True,
                "diversity_ceilings": {"one_sector": 2, "one_strategy_cohort": 2},
                "breakdown": {"correlation_cluster": {}},
            },
            "pladeu_candidate_source_metadata": {
                "candidate_freshness_status": "CURRENT", "market_session_status": "regular",
            },
        })
        self.assertIn("day_swing_exact_symbol_overlap", payload["exact_blockers"])
        self.assertFalse(payload["pilot_enabled"])


if __name__ == "__main__":
    unittest.main()
