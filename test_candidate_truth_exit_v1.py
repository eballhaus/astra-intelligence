from __future__ import annotations

import unittest

import server_extend


class CandidateTruthExitV1Tests(unittest.TestCase):
    def test_batch2_is_advisory_and_never_enables_sells(self):
        payload = server_extend._batch2_truth_exit_capacity_validation_v1_payload({})
        self.assertIn(payload["status"], {"BATCH_2_PASS", "BATCH_2_BLOCKED"})
        self.assertTrue(payload["checks"]["exit_readiness_never_submits_sell"])
        self.assertFalse(payload["behavior_safe_to_apply"])
        self.assertTrue(payload["advisory_only"])

    def test_integrated_summary_requires_both_batch_gates(self):
        payload = server_extend._astra_candidate_truth_exit_validation_v1_payload({})
        self.assertIn(payload["status"], {"PASS", "WARNING"})
        self.assertEqual(payload["batch_1"]["status"], "BATCH_1_PASS")
        self.assertFalse(payload["broker_behavior_changed"])
        self.assertFalse(payload["forced_exits_enabled"])


if __name__ == "__main__":
    unittest.main()
