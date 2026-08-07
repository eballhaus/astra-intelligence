from __future__ import annotations

import unittest
import json
import tempfile
from pathlib import Path

from engine.astra_canonical_natural_lifecycle_v1 import canonical_natural_lifecycle_contract_v1
from engine.astra_runtime_governance_v1 import recovery_status_snapshot


class CanonicalNaturalLifecycleFreezeTests(unittest.TestCase):
    def test_runtime_certified_contract_is_frozen_and_paper_only(self):
        contract = canonical_natural_lifecycle_contract_v1()
        self.assertEqual(contract["contract_name"], "ASTRA_CANONICAL_NATURAL_LIFECYCLE_V1")
        self.assertTrue(contract["freeze_enforced"])
        self.assertTrue(contract["paper_only"])
        self.assertFalse(contract["live_trading_allowed"])
        self.assertEqual([item["symbol"] for item in contract["certified_lane_evidence"]], ["SG", "PTON", "RIVN"])
        self.assertTrue(all(item["strict_truth"] and item["learning_acknowledged"] for item in contract["certified_lane_evidence"]))

    def test_freeze_lists_regression_and_modification_requirements(self):
        contract = canonical_natural_lifecycle_contract_v1()
        self.assertIn("CONFIRMED_RUNTIME_DEFECT", contract["allowed_modification_conditions"])
        self.assertIn("one strict truth per entry/exit fill pair", contract["idempotency_requirements"])
        self.assertGreaterEqual(len(contract["required_regression_suites"]), 5)
        self.assertEqual(contract["provider_calls_used"], 0)
        self.assertEqual(contract["broker_actions_used"], 0)

    def test_recovery_status_is_a_read_only_bounded_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "recovery.json"
            path.write_text(json.dumps({"status": "RECOVERY_READY", "reason": "healthy_runtime", "worker": {"pid": 1}}), encoding="utf-8")
            snapshot = recovery_status_snapshot(path)
        self.assertEqual(snapshot["status"], "RECOVERY_READY")
        self.assertTrue(snapshot["get_route_read_only"])
        self.assertEqual(snapshot["provider_calls_used"], 0)
        self.assertEqual(snapshot["broker_actions_used"], 0)


if __name__ == "__main__":
    unittest.main()
