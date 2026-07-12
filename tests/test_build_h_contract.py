import os
import tempfile
import unittest

from engine.astra_build_h_ownership_v1 import AstraBuildHOwnershipMapV1
from engine.astra_knowledge_warehouse_v1 import AstraKnowledgeWarehouseV1
from engine.astra_intelligence_effectiveness_learning_velocity_v1 import AstraIntelligenceEffectivenessLearningVelocityV1


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

    def test_warehouse_rejects_unknown_dimensions_without_scanning(self):
        with tempfile.TemporaryDirectory() as state_dir:
            result = AstraKnowledgeWarehouseV1(state_dir=state_dir, ttl_seconds=0).query({"not_supported": "x"})
            self.assertEqual(result["status"], "invalid_query")
            self.assertFalse(result["full_history_scan_used"])
            self.assertEqual(result["files_opened"], 0)

    def test_warehouse_query_contract_is_bounded(self):
        with tempfile.TemporaryDirectory() as state_dir:
            result = AstraKnowledgeWarehouseV1(state_dir=state_dir, ttl_seconds=0).status(force=True)
            self.assertTrue(result["manifest_first"])
            self.assertFalse(result["full_history_fallback"])
            self.assertLessEqual(result["bounded_read_policy"]["max_results"], 100)

    def test_storage_profile_is_non_destructive_and_explicit(self):
        with tempfile.TemporaryDirectory() as state_dir:
            result = AstraKnowledgeWarehouseV1(state_dir=state_dir, ttl_seconds=0).status(force=True)
            self.assertIn(result["rotation_status"], {"not_started_non_destructive", "existing_partition_metadata_reused; new partition migration deferred"})
            self.assertFalse(result["incremental_index_status"]["full_rebuild_on_render"])
            self.assertIn("status", result["growth_projection"])

    def test_effectiveness_does_not_count_passive_presence(self):
        module = AstraIntelligenceEffectivenessLearningVelocityV1(state_dir=tempfile.mkdtemp(), ttl_seconds=0)
        result = module.status(statuses={"shadow_vs_paper_performance_attribution_v1": {"evidence_count": 4}}, force=True)
        self.assertTrue(result["passive_presence_excluded"])
        shadow = next(row for row in result["evidence_chain"] if row["evidence_class"] == "shadow")
        self.assertEqual(shadow["consumed"], 0)
        self.assertEqual(shadow["consumption_status"], "available_not_proven")
        self.assertFalse(result["promotion_enabled"])


if __name__ == "__main__":
    unittest.main()
