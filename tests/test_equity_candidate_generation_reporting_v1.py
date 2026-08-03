import unittest
from unittest.mock import patch

import server_extend


class EquityCandidateGenerationReportingTests(unittest.TestCase):
    def setUp(self):
        self.current_rows = [
            {
                "symbol": "LYFT",
                "asset_class": "equity",
                "trade_horizon_style": "day_trade",
                "score": 85.16,
                "source_snapshot_id": "top_buys_runtime:current",
            },
            {
                "symbol": "AMZN",
                "asset_class": "equity",
                "trade_horizon_style": "scalp",
                "score": 90.0,
                "source_snapshot_id": "top_buys_runtime:current",
            },
        ]
        self.stale_trace = {
            "per_candidate_decision_trace": [
                {
                    "symbol": "OLD",
                    "asset_class": "equity",
                    "intended_horizon": "unknown",
                    "decision_reason": "max_new_positions_per_cycle_reached",
                },
            ],
        }

    def test_current_top_buys_beats_zero_row_horizon_bundle(self):
        status = {
            "astra_horizon_lifecycle_capacity_promotion_readiness_bundle_v1": {
                "horizon_opportunity_assignment_engine_v1": {
                    "shadow_scalp_candidates": 0,
                    "shadow_day_trade_candidates": 0,
                    "shadow_swing_trade_candidates": 0,
                },
            },
        }
        with patch.object(server_extend, "_cached_candidate_rows_for_horizon_flow_v1", return_value=self.current_rows), patch.object(server_extend, "_paper_autopilot_last_trace_v1", return_value=self.stale_trace):
            payload = server_extend._horizon_candidate_flow_v1(status)

        self.assertEqual(payload["candidate_flow_source"], "bounded_top_buys_runtime_snapshot")
        self.assertEqual(payload["candidate_count_by_horizon"]["day_trade"], 1)
        self.assertEqual(payload["candidate_count_by_horizon"]["scalp"], 1)

    def test_trade_horizon_style_is_a_canonical_horizon_input(self):
        self.assertEqual(server_extend._candidate_horizon_from_row_v1({"trade_horizon_style": "day_trade"}), "day_trade")
        self.assertEqual(server_extend._candidate_horizon_from_row_v1({"trade_horizon_style": "scalp"}), "scalp")

    def test_current_snapshot_trace_is_not_reported_as_historical_rejection(self):
        with patch.object(server_extend, "_cached_candidate_rows_for_horizon_flow_v1", return_value=self.current_rows), patch.object(server_extend, "_paper_autopilot_last_trace_v1", return_value=self.stale_trace):
            payload = server_extend._candidate_level_horizon_trace_v1_payload({})

        self.assertEqual(payload["source_lineage"]["candidate_source"], "bounded_top_buys_runtime_snapshot")
        self.assertEqual({row["symbol"] for row in payload["candidate_rows"]}, {"LYFT", "AMZN"})
        self.assertTrue(all(row["final_status"] == "CURRENT_CANDIDATE_NOT_EXECUTION_EVALUATED" for row in payload["candidate_rows"]))
        self.assertTrue(all(row["final_reason"] == "candidate_present_in_current_top_buys_snapshot_not_yet_in_execution_trace" for row in payload["candidate_rows"]))


if __name__ == "__main__":
    unittest.main()
