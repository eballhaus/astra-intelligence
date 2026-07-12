import os
import tempfile
import unittest

from engine.astra_build_h_ownership_v1 import AstraBuildHOwnershipMapV1


class BuildHOwnershipContractTests(unittest.TestCase):
    def test_ownership_map_is_bounded_and_safe(self):
        with tempfile.TemporaryDirectory() as state_dir:
            os.makedirs(os.path.join(state_dir, "storage_summary_indexes"), exist_ok=True)
            with open(os.path.join(state_dir, "broker_truth_records_v1.json"), "w", encoding="utf-8") as handle:
                handle.write("{}")
            result = AstraBuildHOwnershipMapV1(state_dir=state_dir, ttl_seconds=0).status(force=True)
            self.assertIn(result["status"], {"OWNERSHIP_MAP_PASS", "OWNERSHIP_MAP_PASS_WITH_WARNINGS"})
            self.assertGreaterEqual(result["stores_inventoried"], 10)
            self.assertTrue(result["no_destructive_migration"])
            self.assertFalse(result["behavior_safe_to_apply"])
            self.assertEqual(result["provider_calls_used"], 0)

    def test_known_authoritative_owner_is_explicit(self):
        result = AstraBuildHOwnershipMapV1(state_dir=tempfile.mkdtemp(), ttl_seconds=0).status(force=True)
        broker = next(row for row in result["stores"] if row["store"] == "broker_truth_records_v1")
        self.assertEqual(broker["authority"], "AUTHORITATIVE")
        self.assertEqual(broker["owner"], "closed_trade_truth_registry_v1")


if __name__ == "__main__":
    unittest.main()
