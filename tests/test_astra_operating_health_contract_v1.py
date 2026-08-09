from __future__ import annotations

import tempfile
import unittest

from engine.astra_operating_health_contract_v1 import AstraOperatingHealthContractV1


class OperatingHealthContractTests(unittest.TestCase):
    def test_strict_truth_is_consumed_once_and_lane_truth_is_preserved(self):
        with tempfile.TemporaryDirectory() as root:
            contract = AstraOperatingHealthContractV1(root)
            payload = contract.build(
                multilane={"lanes": {"CRYPTO": {"current_stage": "lifecycle_closure", "first_blocker": "", "candidate_count": 1, "paper_order_intents": 0}}},
                worker_state={}, continuous={"status": "PASS"}, sentinel={"status": "PASS"}, cortex={"status": "PASS"},
                truth_records=[{"strict_broker_truth": True, "truth_id": "truth-1", "lifecycle_id": "life-1", "lane": "CRYPTO", "symbol": "BTC/USD", "entry_fill_id": "in", "exit_fill_id": "out"}],
                learning_records=[{"truth_id": "truth-1"}],
            )
            self.assertEqual(payload["lanes"]["CRYPTO"]["strict_truth_count"], 1)
            self.assertEqual(payload["lanes"]["CRYPTO"]["truths_consumed_by_learning"], 1)
            self.assertTrue(payload["lanes"]["CRYPTO"]["cortex_acknowledged"])
            self.assertEqual(payload["truth_to_learning_ledger"][0]["final_state"], "CONSUMED")

    def test_open_or_partial_records_are_not_counted_as_strict_truth(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={},
                truth_records=[{"lifecycle_id": "open", "lane": "DAY", "symbol": "AAPL", "entry_fill_id": "in"}],
            )
            self.assertEqual(payload["strict_truth_total"], 0)

    def test_high_sentinel_root_prevents_false_control_plane_agreement(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {"SWING": {"first_blocker": "CANDIDATE_TIMESTAMP_STALE"}}}, worker_state={}, continuous={"status": "PASS"},
                sentinel={"status": "WARNING", "active_root_causes": [{"severity": "HIGH", "category": "MARKET_DATA_STALE"}]},
            )
            self.assertEqual(payload["status"], "WARNING")
            self.assertFalse(payload["control_plane_agreement"])
            self.assertEqual(payload["lanes"]["SWING"]["waiting_state"], "LEGITIMATE_WAIT")

    def test_snapshot_is_read_only_and_missing_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as root:
            payload = AstraOperatingHealthContractV1(root).snapshot()
            self.assertEqual(payload["status"], "AWAITING_WORKER_SNAPSHOT")
            self.assertTrue(payload["get_route_read_only"])
            self.assertEqual(payload["provider_calls_used"], 0)
            self.assertFalse(payload["behavior_safe_to_apply"])

    def test_handoff_ledger_uses_existing_timestamps_and_marks_missing_stages_unobserved(self):
        with tempfile.TemporaryDirectory() as root:
            truth = {
                "evidence_class": "BROKER_CONFIRMED_COMPLETE", "stable_key": "strict:in:out",
                "lifecycle_id": "life-1", "lane_id": "DAY", "symbol": "AAPL",
                "entry_fill_id": "in", "exit_fill_id": "out", "created_at": "2026-08-09T12:00:00Z",
                "learning_acknowledged": True,
            }
            learning = {
                "lifecycle_id": "life-1", "lesson_id": "lesson-1",
                "acknowledged_at": "2026-08-09T12:00:10Z",
                "created_at": "2026-08-09T12:00:20Z",
                "teacher_handoff_complete": True,
            }
            payload = AstraOperatingHealthContractV1(root).build(
                multilane={"lanes": {}}, worker_state={}, continuous={}, sentinel={},
                truth_records=[truth], learning_records=[learning],
            )
            ledger = payload["truth_to_learning_ledger"][0]
            stages = {row["stage"]: row for row in ledger["stages"]}
            self.assertEqual(payload["lanes"]["DAY"]["strict_truth_count"], 1)
            self.assertEqual(stages["learning_acknowledged"]["latency_from_previous_seconds"], 10.0)
            self.assertEqual(stages["canonical_lesson_compressed"]["latency_from_previous_seconds"], 10.0)
            self.assertEqual(stages["teacher_handoff"]["status"], "ACKNOWLEDGED_TIMESTAMP_UNOBSERVED")
            self.assertEqual(ledger["first_delayed_or_unobserved_handoff"], "teacher_handoff")
            self.assertEqual(stages["memory_index_available"]["status"], "UNKNOWN_UNOBSERVED")


if __name__ == "__main__":
    unittest.main()
