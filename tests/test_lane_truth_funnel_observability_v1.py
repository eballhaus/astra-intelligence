import json
import tempfile
import unittest

from engine.lane_execution_trace_ledger_v1 import LaneExecutionTraceLedgerV1


class LaneTruthFunnelObservabilityTests(unittest.TestCase):
    def test_exit_transition_is_compact_and_does_not_change_candidate_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = LaneExecutionTraceLedgerV1(directory)
            ledger.record([{
                "lane_id": "DAY",
                "symbol": "LYFT",
                "candidate_id": "candidate-1",
                "recommendation_id": "recommendation-1",
            }], cycle_id="cycle-1")
            before = ledger.summary()["total_trace_rows"]

            result = ledger.record_exit_lifecycle_transition({
                "position_id": "life-1",
                "lane_id": "DAY",
                "symbol": "LYFT",
                "state": "EXIT_READY",
                "previous_state": "EXIT_REVIEW",
                "decision": "EXIT_READY",
                "reason": "same_session_exit_required",
                "exact_blocker": "",
                "stage_entered_at": "2026-09-24T15:00:00Z",
                "entry_fill_id": "entry-1",
                "exit_order_id": "",
                "exit_fill_id": "",
            })

            self.assertEqual(result["appended"], 1)
            self.assertEqual(ledger.summary()["total_trace_rows"], before)
            with open(ledger.truth_funnel_path, encoding="utf-8") as handle:
                event = json.loads(handle.readline())
            self.assertEqual(event["event_type"], "EXIT_LIFECYCLE_TRANSITION")
            self.assertEqual(event["state"], "EXIT_READY")
            self.assertEqual(event["lifecycle_id"], "life-1")
            self.assertTrue(event["paper_only_preserved"])
            self.assertNotIn("positions", event)

    def test_exit_transition_rejects_incomplete_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            result = LaneExecutionTraceLedgerV1(directory).record_exit_lifecycle_transition({
                "lane_id": "DAY",
                "state": "EXIT_READY",
            })
            self.assertEqual(result["appended"], 0)
            self.assertEqual(result["reason"], "INCOMPLETE_EXIT_TRANSITION_IDENTITY")


if __name__ == "__main__":
    unittest.main()
