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


if __name__ == "__main__":
    unittest.main()
